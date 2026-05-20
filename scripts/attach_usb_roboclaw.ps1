# attach_usb_roboclaw.ps1 - route SO-101 arms + UVC camera to the Ubuntu-roboclaw WSL2 distro.
# Run from an elevated PowerShell window. Requires: usbipd-win, a WSL2 distro named "Ubuntu-roboclaw".
#
# Policy: this script is the counterpart to attach_usb_wsl.ps1 (which targets Ubuntu for
# the unrelated so101-rl-deploy project). Only one distro can own a given BUSID at a time,
# so we explicitly detach any previous attachment before re-attaching to Ubuntu-roboclaw.

param(
    [string]$Distro = "Ubuntu-roboclaw",
    [string[]]$BusIds = @('4-1','4-2','4-3','4-4','5-1','5-3','5-4'),
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

# Wake the distro and keep it alive for the duration of bind/attach.
# `usbipd attach --auto-attach` watchers exit immediately with "selected WSL
# distribution is not running" if the distro is Stopped at spawn time, so we
# must guarantee a live distro BEFORE the attach loop. A backgrounded
# `sleep 7200` in the distro keeps it up for 2 hours (well past anything this
# script does). Idempotent — running multiple times just spawns extra sleeps.
Write-Host "  Waking $Distro to keep its kernel alive during attach..."
Start-Process -WindowStyle Hidden -FilePath "wsl" `
    -ArgumentList @("-d", $Distro, "--", "sh", "-c", "sleep 7200") | Out-Null
Start-Sleep -Seconds 2

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

# Cold-distro USB enumeration takes longer than 3s. Give auto-attach watchers
# time to land devices and udev time to populate /dev/{serial,v4l}/by-*. The
# distro was woken above, so this is just the propagation budget.
Write-Host "  Waiting for udev to populate device symlinks..."
Start-Sleep -Seconds 8

Write-Host ""
Write-Host "=== Verification (inside $Distro) ==="

# Verification is PowerShell-side, NOT a multi-line bash heredoc through
# `bash -c $script`. The heredoc approach was brittle: CRLF preserved through
# PowerShell→wsl→bash made each line's trailing `\r` part of variable values,
# so `arms=${arms:-0}` ended up as `"0\r"`, the `\r` carriage-returned the
# subsequent echo, and the integer test `[ "$arms" -eq 4 ]` choked on `"0\r"`
# with "integer expression expected". One-liner `wsl -- bash -lc 'expr'` calls
# return clean stdout; PowerShell's .Trim() strips any stray whitespace.
$ttyAcm  = (wsl -d $Distro -- bash -lc 'ls -1 /dev/ttyACM* 2>/dev/null' | Out-String).Trim()
$byId    = (wsl -d $Distro -- bash -lc 'ls -1 /dev/serial/by-id/ 2>/dev/null' | Out-String).Trim()
$videos  = (wsl -d $Distro -- bash -lc 'ls -1 /dev/video* 2>/dev/null' | Out-String).Trim()

Write-Host "--- /dev/ttyACM* (arms) ---"
Write-Host ($ttyAcm  ? $ttyAcm  : "(none)")
Write-Host ""
Write-Host "--- /dev/serial/by-id/ (stable arm symlinks) ---"
Write-Host ($byId    ? $byId    : "(none)")
Write-Host ""
Write-Host "--- /dev/video* (raw camera nodes) ---"
Write-Host ($videos  ? $videos  : "(none)")
Write-Host ""

# Count arms by CH343 by-id pattern (one symlink per arm, stable across replug).
$armCount = [int]((wsl -d $Distro -- bash -lc 'ls -1 /dev/serial/by-id/usb-1a86_USB_Single_Serial_*-if00 2>/dev/null | wc -l').Trim())

# Count distinct cameras by VID:PID. DSJ-2062 is 0c45:64ab. Each physical camera
# exposes 2 v4l2 nodes (primary video + metadata), each with its own ID_PATH and
# its own /dev/v4l/by-path/*-video-index0 entry — so counting symlinks or video
# nodes inflates the count 2x. lsusb groups by USB device, which IS the right
# unit of "physical camera". One line per camera, regardless of v4l-node fanout.
# Falls back to sysfs walk if lsusb is absent (some minimal distros don't ship
# usbutils, though our provisioner installs it).
$camCount = [int]((wsl -d $Distro -- bash -lc 'lsusb -d 0c45:64ab 2>/dev/null | wc -l').Trim())
if ($camCount -eq 0) {
    $camCount = [int]((wsl -d $Distro -- bash -lc 'for d in /sys/bus/usb/devices/*; do v=$(cat "$d/idVendor" 2>/dev/null); p=$(cat "$d/idProduct" 2>/dev/null); [ "$v" = "0c45" ] && [ "$p" = "64ab" ] && echo "$d"; done | wc -l' 2>$null).Trim())
}

Write-Host "=== Device counts ==="
Write-Host "arms:     $armCount  (expect 4)"
Write-Host "cameras:  $camCount  (expect 3: 1 scene + 2 wrist)"
if ($armCount -eq 4 -and $camCount -eq 3) {
    Write-Host "[PASS] all devices accounted for" -ForegroundColor Green
    $verifyExit = 0
} else {
    Write-Host "[FAIL] device count mismatch — check usbipd attach state, physical cables, and bus enumeration" -ForegroundColor Red
    $verifyExit = 1
}

Write-Host ""
if ($verifyExit -ne 0) {
    Write-Host "WARNING: verification reported a device count mismatch (exit $verifyExit)." -ForegroundColor Yellow
}
Write-Host "Done. Auto-attach processes are running in the background."
Write-Host "To stop them:  Get-Process usbipd | Stop-Process"
Write-Host "To detach:     .\attach_usb_roboclaw.ps1 -Detach"

# Propagate verification result via $LASTEXITCODE so callers (resume_roboclaw.ps1)
# can branch on it. 0 = [PASS], 1 = [FAIL].
exit $verifyExit
