# Third-party components

The MIT license covers this project's original code. Third-party packages retain their own licenses. Codex and OpenAI names and logos are used to identify the service; their trademarks are not licensed under this project's MIT license. This is an independent community app.

| Component | Purpose | Project / license |
| --- | --- | --- |
| codex-speed by pszemraj | Speed calculations, downloaded at runtime | https://gist.github.com/pszemraj/f8fe69ff5002c3bd0825edfd02001635 — not bundled; consult upstream terms |
| ccusage | Usage and estimated API cost, run through npm | https://github.com/ccusage/ccusage — MIT |
| OpenAI Codex | Account limits and local logs; installed separately | https://github.com/openai/codex — Apache-2.0 |
| Python / Tk | Language runtime and desktop UI | https://www.python.org/ — PSF and Tcl/Tk licenses |
| pystray | Notification-area icon | https://github.com/moses-palmer/pystray — LGPL-3.0 |
| Pillow | Image and icon loading | https://python-pillow.org/ — MIT-CMU |
| Rich | Speed tool console formatting | https://github.com/Textualize/rich — MIT |
| joblib / cloudpickle | Speed tool runtime | https://github.com/joblib/joblib — BSD-3-Clause; https://github.com/cloudpipe/cloudpickle — BSD-3-Clause |
| tzdata | Timezone database | https://github.com/python/tzdata — Apache-2.0; IANA data public domain |
| PyInstaller | Windows packaging | https://pyinstaller.org/ — GPL with bootloader exception |

The Windows release uses a folder bundle with an external Python shared library. Dependency license files are included under `licenses/`. Python package wheels and source are available from each upstream project. To change pystray or another bundled Python package, install the replacement in the app's `_internal/` folder with the same module name, or rebuild from the published source and `requirements.txt`. The build does not embed codex-speed or ccusage source.
