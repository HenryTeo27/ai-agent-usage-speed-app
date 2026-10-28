param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$Python = (Get-Command $Python).Source
$root = Split-Path $PSScriptRoot
Set-Location $root
# Some Codex runtimes patch ssl.py to load an adjacent certificate file.
$certFile = Join-Path (Split-Path $Python) 'Lib\codex-rejected-cas.pem'
$certArgs = @()
if (Test-Path -LiteralPath $certFile) { $certArgs = @('--add-data', ($certFile+';.')) }
& $Python -m PyInstaller @certArgs --noconfirm --clean --onedir --windowed --name CodexMeter --exclude-module numpy --exclude-module pandas --exclude-module matplotlib --exclude-module scipy --exclude-module IPython --exclude-module pytest --icon assets/codex-transparent.ico --add-data 'assets;assets' --paths vendor --paths build_vendor --collect-all rich --collect-all joblib --collect-all tzdata --hidden-import orjson --hidden-import zoneinfo --hidden-import statistics --hidden-import csv --hidden-import gzip --hidden-import argparse --hidden-import dataclasses --hidden-import pystray._win32 --copy-metadata pystray --copy-metadata Pillow --copy-metadata rich --copy-metadata joblib --copy-metadata tzdata meter.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
$release = Join-Path $root 'release\Codex-Meter-Windows-x64'
$release = [IO.Path]::GetFullPath($release)
$expected = [IO.Path]::GetFullPath((Join-Path $root 'release\Codex-Meter-Windows-x64'))
if ($release -ne $expected) { throw 'Unexpected release staging path.' }
if (Test-Path -LiteralPath $release) { Remove-Item -LiteralPath $release -Recurse -Force }
New-Item -ItemType Directory -Force $release | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'dist\CodexMeter') -Destination $release -Recurse -Force
foreach ($file in @('Install.cmd','install.ps1','README.md','LICENSE','THIRD_PARTY_NOTICES.md')) {
    Copy-Item -LiteralPath (Join-Path $root $file) -Destination $release -Force
}
Copy-Item -LiteralPath (Join-Path $root 'docs') -Destination $release -Recurse -Force
$licenses = Join-Path $release 'licenses'
New-Item -ItemType Directory -Force $licenses | Out-Null
& $Python -c "import importlib.metadata as m,pathlib,shutil; out=pathlib.Path(r'$licenses'); names=['pystray','Pillow','rich','joblib','cloudpickle','tzdata','PyInstaller','six','markdown-it-py','mdurl','pygments','orjson']; [(shutil.copytree(d._path,out / d.metadata['Name'],dirs_exist_ok=True)) for d in (m.distribution(n) for n in names)]"
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
Copy-Item -LiteralPath (Join-Path (Split-Path $Python) 'LICENSE.txt') -Destination (Join-Path $licenses 'Python-LICENSE.txt') -ErrorAction SilentlyContinue
$archive = Join-Path $root 'release\Codex-Meter-Windows-x64.zip'
Compress-Archive -Path (Join-Path $release '*') -DestinationPath $archive -Force
Get-FileHash -LiteralPath $archive -Algorithm SHA256
