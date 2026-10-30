"""Exercise the update ZIP and its bundled health check without opening a window."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app_updater
import meter

parser=argparse.ArgumentParser();parser.add_argument('--archive',required=True);parser.add_argument('--check-latest',action='store_true');args=parser.parse_args()
archive=Path(args.archive).resolve()
digest=hashlib.sha256()
with archive.open('rb') as stream:
    for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
candidate={'version':meter.VERSION,'size':archive.stat().st_size,'sha256':digest.hexdigest(),'url':'local-test'}
with tempfile.TemporaryDirectory(prefix='meter-update-package-') as folder:
    def health(executable,version,stage):
        output=stage/'health.json'
        process=subprocess.Popen([str(executable),'--health-check','--worker-output',str(output)],
                                 env={**os.environ,'CODEX_METER_DATA_DIR':str(Path(folder)/'state')},
                                 creationflags=app_updater.CREATE_NO_WINDOW)
        assert process.wait(timeout=45)==0
        result=json.loads(output.read_text(encoding='utf-8-sig'))
        assert result['ok'] and result['value']=={'version':version,'pid':process.pid},result
        output.unlink()
    with patch.object(app_updater,'open_url',side_effect=lambda *args,**kwargs:archive.open('rb')):
        stage=app_updater.download_and_stage(candidate,Path(folder)/'state',health)
    assert (stage/'CodexMeter'/'_internal'/'scripts'/'apply-update.ps1').is_file()
    if args.check_latest:
        output=Path(folder)/'latest.json'
        process=subprocess.Popen([str(stage/'CodexMeter'/'CodexMeter.exe'),'--app-update','--worker-output',str(output)],
                                 env={**os.environ,'CODEX_METER_DATA_DIR':str(Path(folder)/'state')},
                                 creationflags=app_updater.CREATE_NO_WINDOW)
        assert process.wait(timeout=60)==0
        result=json.loads(output.read_text(encoding='utf-8-sig'))
        assert result['ok'],result
    app_updater.remove_stage(stage,Path(folder)/'state'/'updates')
print('Packaged update: archive digest, safe extraction, helper and hidden startup check passed.')
