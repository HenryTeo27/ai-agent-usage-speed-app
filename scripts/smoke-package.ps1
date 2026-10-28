param([Parameter(Mandatory=$true)][string]$Executable)
$ErrorActionPreference = 'Stop'
$folder = Join-Path ([IO.Path]::GetTempPath()) ('codex-meter-smoke-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $folder | Out-Null
$script = Join-Path $folder 'smoke.py'
@'
import argparse, csv, dataclasses, gzip, statistics, zoneinfo
import joblib, rich, tzdata
from rich.console import Console
Console().print('runtime-ready')
'@ | Set-Content -Encoding utf8 $script
$result = Join-Path $folder 'result.json'
Start-Process -FilePath $Executable -ArgumentList @('--speed-worker',('"'+$script+'"'),'--worker-output',('"'+$result+'"')) -WindowStyle Hidden -Wait
$data = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
if (-not $data.ok -or $data.value -notmatch 'runtime-ready') { throw ('Packaged runtime failed: ' + $data.error) }
Write-Host 'Packaged speed runtime passed.'
