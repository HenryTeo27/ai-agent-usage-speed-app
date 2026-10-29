"""Run two independent processes; never open an app window or touch real data."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument('--exe')
args=parser.parse_args()
worker=Path(__file__).with_name('lifecycle_worker.py').resolve()
with tempfile.TemporaryDirectory(prefix='meter-reopen-') as folder:
    env={**os.environ,'CODEX_METER_DATA_DIR':str(Path(folder)/'state')}
    for stage in ('write','read'):
        if args.exe:
            result=Path(folder)/(stage+'.json')
            command=[args.exe,'--speed-worker',str(worker),stage,'--worker-output',str(result)]
        else: command=[sys.executable,str(worker),stage]
        process=subprocess.run(command,env=env,cwd=folder,capture_output=True,text=True,
                               creationflags=0x08000000 if os.name=='nt' else 0,timeout=30)
        if process.returncode: raise RuntimeError(process.stderr or process.stdout)
        if args.exe:
            data=json.loads(result.read_text(encoding='utf-8-sig'))
            if not data.get('ok'): raise RuntimeError(data.get('error'))
            output=json.loads(data['value'])
        else: output=json.loads(process.stdout)
        assert output['passed']
    assert sorted(path.name for path in (Path(folder)/'state').iterdir())==['settings.json','snapshot.json']
print('Quit/reopen, immediate settings save, cached labels and all appearance modes passed in two isolated processes.')
