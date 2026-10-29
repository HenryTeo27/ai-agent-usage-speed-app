"""Developer-only sampled process measurements. Requires psutil; not shipped in the app."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build_vendor'))
import psutil

parser = argparse.ArgumentParser()
parser.add_argument('--pid', type=int)
parser.add_argument('--exe')
parser.add_argument('--seconds', type=float, default=20)
args = parser.parse_args()

if args.pid:
    process = psutil.Process(args.pid)
    before = sum(process.cpu_times()[:2])
    start = time.monotonic()
    time.sleep(args.seconds)
    memory = process.memory_info()
    print(json.dumps(dict(seconds=round(time.monotonic()-start, 2),
                         cpu_seconds=round(sum(process.cpu_times()[:2])-before, 5),
                         working_set_mib=round(memory.rss/2**20, 2),
                         private_mib=round(memory.private/2**20, 2),
                         threads=process.num_threads(), handles=process.num_handles())))
else:
    temp_parent=Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix='codex-meter-profile-',dir=str(temp_parent)) as folder:
        if Path(folder).resolve().parent != temp_parent:
            raise RuntimeError('Unexpected diagnostic temporary directory')
        output = Path(folder) / 'result.json'
        child = subprocess.Popen([args.exe, '--diagnose', '--worker-output', str(output)],
                                 creationflags=0x08000000)
        root = psutil.Process(child.pid)
        tracked = {}
        cpu = {}
        peaks = dict(working_set_mib=0, private_mib=0, processes=0)
        start = time.monotonic()
        while child.poll() is None:
            try:
                for process in [root] + root.children(recursive=True):
                    tracked[(process.pid, process.create_time())] = process
            except psutil.Error:
                pass
            rss = private = count = 0
            for key, process in list(tracked.items()):
                try:
                    if process.create_time() != key[1]:
                        continue
                    memory = process.memory_info()
                    rss += memory.rss
                    private += memory.private
                    count += 1
                    cpu[key] = sum(process.cpu_times()[:2])
                except psutil.Error:
                    pass
            peaks['working_set_mib'] = max(peaks['working_set_mib'], rss/2**20)
            peaks['private_mib'] = max(peaks['private_mib'], private/2**20)
            peaks['processes'] = max(peaks['processes'], count)
            time.sleep(0.2)
        result = json.loads(output.read_text())
        print(json.dumps(dict(seconds=round(time.monotonic()-start, 2),
                              sampled_cpu_seconds=round(sum(cpu.values()), 3),
                              peak={key: round(value, 2) for key, value in peaks.items()},
                              sources={key: dict(ok=value['ok'], seconds=value['seconds'])
                                       for key, value in result['value'].items()})))
