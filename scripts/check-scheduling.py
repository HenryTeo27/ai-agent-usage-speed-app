"""Run the source or packaged hidden-loop check with fake data and no desktop UI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser=argparse.ArgumentParser();parser.add_argument('--exe');args=parser.parse_args()
worker=Path(__file__).with_name('schedule_worker.py').resolve()
with tempfile.TemporaryDirectory(prefix='meter-schedule-') as folder:
    env={**os.environ,'CODEX_METER_DATA_DIR':str(Path(folder)/'state')}
    if args.exe:
        output=Path(folder)/'result.json'
        command=[args.exe,'--speed-worker',str(worker),'--worker-output',str(output)]
    else: command=[sys.executable,str(worker)]
    run=subprocess.run(command,env=env,cwd=folder,capture_output=True,text=True,
                       creationflags=0x08000000 if os.name=='nt' else 0,timeout=20)
    if run.returncode: raise RuntimeError(run.stderr or run.stdout)
    if args.exe:
        result=json.loads(output.read_text(encoding='utf-8-sig'))
        if not result.get('ok'): raise RuntimeError(result.get('error'))
        value=json.loads(result['value'])
    else: value=json.loads(run.stdout)
    assert value['passed']
print('Hidden event loop: changed 4h to 2h after 3h, saved the setting, and completed one automatic refresh.')
