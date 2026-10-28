# Codex Meter plan and completion notes

- [x] Native compact Windows window, tray open/refresh/quit, single-instance reopening.
- [x] Remaining Codex allowance; current-month and all-time tokens and USD estimates.
- [x] Configurable all-time reserve adjustment; token delta from last successful usage scan.
- [x] 1-day and 14-day Selected history speeds, hover details and colored ratios.
- [x] Manual or 2/4/6/8/12-hour refresh; background workers, command timeouts and retained previous results.
- [x] Transparent multi-resolution Windows icon.
- [x] Source and dependency credits below the data, using natural mouse-wheel scrolling with no visible scrollbar.
- [x] Latest-tool checks with a last-working speed-script fallback; no separate speed-tool installation required.
- [x] Windows executable ZIP, desktop and Start menu shortcuts, source installer and MIT license.
- [x] README with quick download, Codex-assisted source installation, data semantics and limitations.
- [x] Verify packaged workers, real speed and account data, desktop installation and five-launch single-instance behavior.

Final delivery: publish the source commit and Windows release to the public GitHub repository.

Only the latest snapshot and settings are retained, plus the working speed script. Temporary sample outputs and caches are removed after scans. npm retains its own package cache. Resource use during scans depends on log size. No long-term power benchmark has been performed.

## v1.0.1 refresh repair

- Include the certificate data required by the Codex-patched Python runtime. Keep TLS verification enabled.
- Run usage, limits and speed concurrently and display each result as it arrives.
- Parse recent speed logs once; use the upstream statistics for both rolling windows. Use orjson only for JSON decoding.
- Distinguish successful data refresh with tool fallback from a failed source. Expose current failure details on hover.
- Validate the packaged executable against real data, not only mocked source tests. Recorded diagnostic times: limits 2.78s, speed 18.36s, usage 42.59s. Times depend on the logs and network.
- On the first launch after a version change, refresh once to verify and replace previous results.

## v1.0.2 resource optimization

- Lazy GUI imports for worker and duplicate launches; small ICO images for tray/header.
- One isolated speed worker; defer hidden redraws and reduce active-only polling.
- Track and terminate owned scan process trees on quit.
- Verified successful real packaged scans, hidden restoration and 10 regression tests.
- Recorded visible/tray idle samples and sampled refresh-tree resource use in docs/performance.md. No hardware power measurement was performed.
