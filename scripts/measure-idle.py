"""Sample an isolated, withdrawn packaged window; the test adds no tray icon."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build_vendor'))
import psutil

parser=argparse.ArgumentParser();parser.add_argument('--exe',required=True);args=parser.parse_args()
worker=Path(__file__).with_name('idle_worker.py').resolve()
with tempfile.TemporaryDirectory(prefix='meter-idle-') as folder:
    folder=Path(folder);ready=folder/'ready';output=folder/'result.json'
    env={**os.environ,'CODEX_METER_DATA_DIR':str(folder/'state'),'CODEX_METER_IDLE_READY':str(ready)}
    process=subprocess.Popen([args.exe,'--speed-worker',str(worker),'--worker-output',str(output)],
                             env=env,creationflags=0x08000000 if os.name=='nt' else 0)
    try:
        limit=time.monotonic()+10
        while not ready.exists() and process.poll() is None and time.monotonic()<limit: time.sleep(0.1)
        if not ready.exists(): raise RuntimeError('Idle worker did not start')
        time.sleep(1)
        measured=psutil.Process(process.pid);before=sum(measured.cpu_times()[:2]);start=time.monotonic()
        time.sleep(10)
        memory=measured.memory_info()
        result={'seconds':round(time.monotonic()-start,2),'cpu_seconds':round(sum(measured.cpu_times()[:2])-before,5),
                'working_set_mib':round(memory.rss/2**20,2),'private_mib':round(memory.private/2**20,2),
                'tray_icon_included':False}
        if process.wait(timeout=15): raise RuntimeError('Idle worker failed')
        assert json.loads(output.read_text(encoding='utf-8-sig'))['ok']
        print(json.dumps(result))
    finally:
        if process.poll() is None:
            process.terminate();process.wait(timeout=5)
