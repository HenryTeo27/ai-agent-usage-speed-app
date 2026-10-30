# Resource checks for v1.0.2

Windows 11 x64, bundled Python 3.12. Measurements taken on October 28, 2026, after successful refreshes. These are short spot checks on a working computer, not a controlled battery or wattage test.

## Main app at rest

| Version / state | Working set | Private memory | CPU time added in 20 seconds |
| --- | ---: | ---: | ---: |
| v1.0.1, window visible | 64.13 MiB | 39.84 MiB | 0.00000 s |
| v1.0.2, window visible | 42.82 MiB | 23.20 MiB | 0.04688 s |
| v1.0.2, hidden in tray | 40.52 MiB | 22.98 MiB | 0.00000 s |

The visible-window working set was about 33% lower and private memory about 42% lower in these samples. CPU time is cumulative processor time, not the wall-clock sample duration. The visible v1.0.2 sample averaged about 0.23% of one CPU core. Working set includes shared pages; private memory is memory owned by the process. Windows can change these values over time.

## During refresh

A sampled v1.0.2 diagnostic refresh process tree peaked at about 318 MiB working set and 320 MiB private memory, including external commands and all their children. All sources succeeded. That run took about 60 seconds; a subsequent installed-app refresh took 46.7 seconds. Logs and network activity changed during testing, so these runs are not a controlled speed comparison.

The external tools still read and parse local logs. This computer had roughly 5.5 GB of recent Codex logs during the previous refresh investigation. The app does not impose a memory or CPU cap on ccusage; adding one could slow or fail the scan. Refresh resource use is substantially higher than idle use.

## Changes

- Load Tk, pystray and image modules only for the main window. Scan and duplicate-launch processes skip them; a short-lived update health check imports them without opening a window.
- Decode a small ICO frame for the tray and header instead of retaining the full-resolution PNG.
- Run speed download and parsing in one isolated worker. Its parsing memory is released when it exits.
- Keep the window and its widgets in place during refresh. Update changed values and table rows only; while hidden or minimized, defer those updates until the window is restored.
- Check refresh results every 0.5 seconds while visible and every 1 second while hidden. Stop checking results when the refresh finishes. In automatic mode, a lightweight deadline timer runs at most once per minute between scans; it starts no worker until due. Manual mode has no deadline timer.
- Run app-update downloads and archive checks in a temporary worker. Its networking and archive libraries leave memory when it exits. An idle deadline timer wakes at most once per hour and does not contact the network until a check is due.
- Terminate owned command trees when the user quits, including npm/native-tool children. A regression test verifies this behavior.
- Preserve single-pass speed parsing, upstream statistics, latest-tool checks and immediate per-source updates.

## Reproduce

The measurement helper is for development only. `psutil` is not included in the application.

```powershell
pip install psutil
python scripts/measure_resources.py --pid <main-process-id> --seconds 20
python scripts/measure_resources.py --exe C:\path\to\CodexMeter.exe
```

The refresh helper samples the process tree every 0.2 seconds. It can miss very short-lived processes and transient peaks; summed CPU time is a sampled estimate. It prints resource counts and source success/timing, not chat content.
