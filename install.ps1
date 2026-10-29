param([switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
$targetRoot = Join-Path $env:LOCALAPPDATA 'Programs\CodexMeter'
$packaged = Join-Path $sourceRoot 'CodexMeter\CodexMeter.exe'
New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
if (Test-Path -LiteralPath $packaged) {
    Copy-Item -Path (Join-Path $sourceRoot 'CodexMeter\*') -Destination $targetRoot -Recurse -Force
    $launcher = Join-Path $targetRoot 'CodexMeter.exe'
    $arguments = ''
    $icon = Join-Path $targetRoot '_internal\assets\codex-clean.ico'
} else {
    foreach ($file in @('meter.py', 'system_theme.py', 'requirements.txt')) {
        Copy-Item -LiteralPath (Join-Path $sourceRoot $file) -Destination $targetRoot -Force
    }
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'assets') -Destination $targetRoot -Recurse -Force
    $python = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        $found = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $found) { throw 'Source installation needs Python 3.10+ with Tk. Use the Windows release ZIP to skip Python setup.' }
        $python = $found.Source
    }
    $runtime = Join-Path $targetRoot 'runtime'
    if (-not (Test-Path -LiteralPath (Join-Path $runtime 'Scripts\python.exe'))) {
        & $python -m venv $runtime
        if ($LASTEXITCODE -ne 0) { throw 'Could not create Python runtime.' }
    }
    & (Join-Path $runtime 'Scripts\python.exe') -m pip install -r (Join-Path $targetRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    $launcher = Join-Path $runtime 'Scripts\pythonw.exe'
    $arguments = '"' + (Join-Path $targetRoot 'meter.py') + '"'
    $icon = Join-Path $targetRoot 'assets\codex-clean.ico'
}
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $folder 'Codex Meter.lnk'))
    $shortcut.TargetPath = $launcher
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $targetRoot
    $shortcut.IconLocation = $icon
    $shortcut.Description = 'Codex usage and speed'
    $shortcut.Save()
}
# Pinned shortcuts can keep their own fixed icon instead of the window's WM_SETICON.
$pinnedFolder = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'
if (Test-Path -LiteralPath $pinnedFolder) {
    $meterShell = New-Object -ComObject WScript.Shell
    foreach ($meterLink in Get-ChildItem -LiteralPath $pinnedFolder -Filter '*.lnk') {
        $meterPinned = $meterShell.CreateShortcut($meterLink.FullName)
        if ($meterPinned.TargetPath -eq $launcher -and ($arguments -eq '' -or $meterPinned.Arguments -eq $arguments)) {
            $meterPinned.IconLocation = $icon
            $meterPinned.Save()
        }
    }
}
if (-not $NoLaunch) {
    if ($arguments) { Start-Process -FilePath $launcher -ArgumentList $arguments -WorkingDirectory $targetRoot }
    else { Start-Process -FilePath $launcher -WorkingDirectory $targetRoot }
}
Write-Host 'Installed. Open Codex Meter from your desktop or Start menu.'
