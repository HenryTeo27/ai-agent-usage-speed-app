param(
    [Parameter(Mandatory=$true)][int]$ParentPid,
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$Stage,
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][int]$Relaunch
)
$ErrorActionPreference = 'Stop'
$targetPath = [IO.Path]::GetFullPath($Target).TrimEnd('\')
$stagePath = [IO.Path]::GetFullPath($Stage).TrimEnd('\')
$expectedTarget = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs\CodexMeter')).TrimEnd('\')
$expectedStages = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'CodexMeter\updates')).TrimEnd('\')
if ($targetPath -ine $expectedTarget -or [IO.Path]::GetDirectoryName($stagePath) -ine $expectedStages -or
    [IO.Path]::GetFileName($stagePath) -notmatch '^update-[0-9a-f]{32}$' -or
    $Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$' -or $Relaunch -notin @(0,1)) {
    throw 'Unexpected updater arguments.'
}
$stageItem = Get-Item -LiteralPath $stagePath
if (-not $stageItem.PSIsContainer -or ($stageItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Unexpected update staging directory.'
}
$payload = Join-Path $stagePath 'CodexMeter'
$payloadItem = Get-Item -LiteralPath $payload
if (-not $payloadItem.PSIsContainer -or ($payloadItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    -not (Test-Path -LiteralPath (Join-Path $payload 'CodexMeter.exe') -PathType Leaf)) {
    throw 'Update payload is missing.'
}

function Move-WithRetry([string]$From, [string]$To) {
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try { Move-Item -LiteralPath $From -Destination $To -ErrorAction Stop; return }
        catch { if ($attempt -eq 19) { throw }; Start-Sleep -Milliseconds 250 }
    }
}
function Start-Hidden([string]$Executable, [string]$Arguments) {
    Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $targetPath -WindowStyle Hidden -PassThru
}
function Save-Failure {
    $failure = Join-Path $expectedStages 'last-failure.json'
    $temp = Join-Path $expectedStages ('failure-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        @{version=$Version; checked_at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()} |
            ConvertTo-Json -Compress | Set-Content -LiteralPath $temp -Encoding utf8
        Move-Item -LiteralPath $temp -Destination $failure -Force
    } catch { } finally { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
}
function Update-Shortcuts {
    $shell = New-Object -ComObject WScript.Shell
    $links = @()
    foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
        $link = Join-Path $folder 'Codex Meter.lnk'
        if (Test-Path -LiteralPath $link) { $links += $link }
    }
    $pinned = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'
    if (Test-Path -LiteralPath $pinned) { $links += @(Get-ChildItem -LiteralPath $pinned -Filter '*.lnk' | ForEach-Object FullName) }
    $exe = Join-Path $targetPath 'CodexMeter.exe'
    $oldPython = Join-Path $targetPath 'runtime\Scripts\pythonw.exe'
    foreach ($link in $links) {
        try {
            $shortcut = $shell.CreateShortcut($link)
            if ($shortcut.TargetPath -ieq $exe -or
                ($shortcut.TargetPath -ieq $oldPython -and $shortcut.Arguments -like '*meter.py*')) {
                $shortcut.TargetPath = $exe
                $shortcut.Arguments = ''
                $shortcut.WorkingDirectory = $targetPath
                $shortcut.IconLocation = Join-Path $targetPath '_internal\assets\codex-gradient.ico'
                $shortcut.Save()
            }
        } catch { }
    }
}

$parent = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
if ($parent -and -not $parent.WaitForExit(60000)) { throw 'Previous app did not exit.' }
if (-not (Test-Path -LiteralPath $targetPath -PathType Container)) { throw 'Installed app no longer exists.' }
$targetItem = Get-Item -LiteralPath $targetPath
if ($targetItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unexpected installed app directory.' }
$backup = Join-Path ([IO.Path]::GetDirectoryName($targetPath)) ('.CodexMeter-backup-' + [Guid]::NewGuid().ToString('N'))
$failed = Join-Path $stagePath 'failed-update'
$exe = Join-Path $targetPath 'CodexMeter.exe'
$backedUp = $false
$installed = $false
$completed = $false
$newProcess = $null
try {
    Move-WithRetry $targetPath $backup
    $backedUp = $true
    Move-WithRetry $payload $targetPath
    $installed = $true
    if ($Relaunch -eq 1) {
        $marker = Join-Path $stagePath 'ready.json'
        $newProcess = Start-Hidden $exe ('--start-hidden --update-ready "' + $marker + '"')
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        $ready = $false
        while ([DateTime]::UtcNow -lt $deadline) {
            if (Test-Path -LiteralPath $marker) {
                try {
                    $result = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
                    if ($result.version -eq $Version -and $result.pid -eq $newProcess.Id) { $ready = $true; break }
                } catch { }
            }
            $newProcess.Refresh()
            if ($newProcess.HasExited) { break }
            Start-Sleep -Milliseconds 250
        }
        if (-not $ready) {
            if (-not $newProcess.HasExited) { Stop-Process -Id $newProcess.Id -Force; $newProcess.WaitForExit(10000) | Out-Null }
            $other = @(Get-Process -Name 'CodexMeter' -ErrorAction SilentlyContinue | Where-Object {
                try { $_.Id -ne $newProcess.Id -and $_.Path -ieq $exe } catch { $false }
            })
            if (-not $other.Count) { throw 'Updated app did not start; restoring the previous version.' }
        }
    }
    try { Update-Shortcuts } catch { }
    $completed = $true
    Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
} catch {
    Save-Failure
    if ($installed -and (Test-Path -LiteralPath $targetPath)) { Move-WithRetry $targetPath $failed }
    if ($backedUp -and (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $targetPath)) {
        Move-WithRetry $backup $targetPath
    }
    if ($Relaunch -eq 1 -and (Test-Path -LiteralPath $exe -PathType Leaf)) {
        try { Start-Hidden $exe '--start-hidden' | Out-Null } catch { }
    }
    throw
} finally {
    # Only remove our own verified staging directory after a successful replacement
    # or a successful rollback. Keep files if recovery could not finish.
    if ($completed -or ($backedUp -and (Test-Path -LiteralPath $targetPath) -and -not (Test-Path -LiteralPath $backup))) {
        Remove-Item -LiteralPath $stagePath -Recurse -Force -ErrorAction SilentlyContinue
    }
}
