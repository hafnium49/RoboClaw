# attach_usb_roboclaw.ps1 - route SO-101 arms + UVC camera to the Ubuntu-roboclaw WSL2 distro.
# Run from an elevated PowerShell window. Requires: usbipd-win, a WSL2 distro named "Ubuntu-roboclaw".
#
# Policy: this script is the counterpart to attach_usb_wsl.ps1 (which targets Ubuntu for
# the unrelated so101-rl-deploy project). Only one distro can own a given BUSID at a time,
# so we explicitly detach any previous attachment before re-attaching to Ubuntu-roboclaw.

param(
    [string]$Distro = "Ubuntu-roboclaw",
    [string[]]$BusIds = @('4-3','4-4','5-1','5-3','5-4'),
    [switch]$Detach
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $principal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "This script must be run from an elevated PowerShell (Run as Administrator)."
    }
}

function Assert-CommandOnPath($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Required command '$name' not found on PATH."
    }
}

function Test-Distro($name) {
    $distros = wsl --list --quiet 2>$null
    return ($distros -split "`r?`n" | ForEach-Object { $_.Trim() }) -contains $name
}

Assert-Admin
Assert-CommandOnPath usbipd
Assert-CommandOnPath wsl

if (-not (Test-Distro $Distro)) {
    throw "WSL distro '$Distro' not found. Create it first (see deployment plan step 1)."
}

if ($Detach) {
    Write-Host "Detaching BUSIDs from any distro..."
    foreach ($b in $BusIds) { usbipd detach --busid $b 2>$null | Out-Null }
    Write-Host "Detach complete."
    return
}

Write-Host "=== Attaching USB devices to $Distro ==="
Write-Host "  Target BUSIDs: $($BusIds -join ', ')"
Write-Host ""

# Clear any stale sessions (e.g. left over from a usbipd service restart after Windows Update).
# Then detach each target BUSID so we never collide with a prior attachment (e.g. to Ubuntu).
Write-Host "  Clearing stale usbipd sessions..."
usbipd detach --all 2>$null | Out-Null
foreach ($b in $BusIds) { usbipd detach --busid $b 2>$null | Out-Null }

foreach ($b in $BusIds) {
    Write-Host "  [$b] binding (persistent)..." -NoNewline
    try {
        usbipd bind --busid $b --force | Out-Null
        Write-Host " OK"
    } catch {
        Write-Host " FAILED: $_" -ForegroundColor Red
        continue
    }

    Write-Host "  [$b] attaching to $Distro (auto-reattach on replug)..." -NoNewline
    # --auto-attach runs in the foreground; spawn each as an independent hidden process so
    # they persist after this script returns. Killing them requires `Stop-Process` by name.
    Start-Process -WindowStyle Hidden -FilePath "usbipd" `
        -ArgumentList @("attach", "--wsl", $Distro, "--busid", $b, "--auto-attach") | Out-Null
    Write-Host " spawned"
}

Start-Sleep -Seconds 3

Write-Host ""
Write-Host "=== Verification (inside $Distro) ==="
wsl -d $Distro -- bash -c "ls -l /dev/ttyACM* /dev/video* 2>/dev/null; echo ''; ls -l /dev/serial/by-id/ 2>/dev/null"

Write-Host ""
Write-Host "Done. Auto-attach processes are running in the background."
Write-Host "To stop them:  Get-Process usbipd | Stop-Process"
Write-Host "To detach:     .\attach_usb_roboclaw.ps1 -Detach"
