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
