# resume_roboclaw.ps1 — one-command day-N resume for the RoboClaw deployment.
# Run from an elevated PowerShell. Wraps the five steps an operator would
# otherwise type manually: pull repo, wake distro, attach USB, start container,
# verify /api/health.
#
# Idempotent. Re-running when everything's already healthy is a fast no-op.
# Each step prints a one-line outcome; final summary is the PASS/FAIL contract
# you can paste into Jira's HUM-2 acceptance.

param(
    [string]$Distro     = "Ubuntu-roboclaw",
    [string]$RepoDistro = "Ubuntu",
    [string]$RepoPath   = "/home/hafnium/RoboClaw",
    [switch]$SkipPull,
    [int]$HealthTimeoutSec = 30
)

$ErrorActionPreference = "Stop"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# Force wsl.exe to emit UTF-8 instead of UTF-16-LE. Without this, the distro-state
# parsing below would see mojibake and miss the "Running" match.
$env:WSL_UTF8 = "1"

function Write-Step($n, $msg) { Write-Host "[$n] $msg" -ForegroundColor Cyan }
function Write-OK($msg)       { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Skip($msg)     { Write-Host "  SKIP: $msg" -ForegroundColor DarkGray }
function Write-Fail($msg)     { Write-Host "  FAIL: $msg" -ForegroundColor Red }

function Assert-Admin {
    $principal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from an elevated PowerShell (Run as Administrator). Required by usbipd bind."
    }
}

Assert-Admin
$startedAt = Get-Date
Write-Host "=== RoboClaw resume — $startedAt ===" -ForegroundColor White

# ----- Step 1: git pull on the in-Ubuntu repo clone -----
Write-Step 1 "Sync repo (skip with -SkipPull)"
if ($SkipPull) {
    Write-Skip "git pull skipped by -SkipPull"
} else {
    $pullOut = wsl -d $RepoDistro --cd $RepoPath -- git pull origin main 2>&1
    if ($LASTEXITCODE -eq 0) {
        $head = (wsl -d $RepoDistro --cd $RepoPath -- git rev-parse --short HEAD).Trim()
        Write-OK "repo at HEAD $head"
    } else {
        Write-Fail "git pull failed: $pullOut"
        exit 1
    }
}

# ----- Step 2: wake Ubuntu-roboclaw and keep it alive -----
Write-Step 2 "Wake $Distro"
$distroState = (wsl --list --verbose 2>&1 | Out-String) -split "`n" | Where-Object { $_ -match $Distro }
if ($distroState -match "Running") {
    Write-Skip "$Distro already Running"
} else {
    Start-Process -WindowStyle Hidden -FilePath "wsl" `
        -ArgumentList @("-d", $Distro, "--", "sh", "-c", "sleep 7200") | Out-Null
    Start-Sleep -Seconds 3
    Write-OK "$Distro woken via backgrounded sleep"
}

# ----- Step 3: run the USB attach script -----
Write-Step 3 "Attach USB devices via attach_usb_roboclaw.ps1"
$attachScript = "\\wsl.localhost\$RepoDistro$($RepoPath -replace '/','\')\scripts\attach_usb_roboclaw.ps1"
& $attachScript
$attachExit = $LASTEXITCODE
if ($attachExit -ne 0) {
    Write-Fail "attach script exited $attachExit — devices may be incomplete. Continuing to check container state."
} else {
    Write-OK "attach reported [PASS]"
}

# ----- Step 4: docker compose up the service -----
Write-Step 4 "Start roboclaw-web container"
$composeOut = wsl -d $Distro -- bash -lc "cd ~/RoboClaw && sg docker -c 'docker compose up -d roboclaw-web'" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-OK ($composeOut -join " | ")
} else {
    Write-Fail "docker compose failed: $composeOut"
    exit 1
}

# ----- Step 5: poll /api/health until healthy or timeout -----
Write-Step 5 "Poll http://localhost:8765/api/health (timeout ${HealthTimeoutSec}s)"
$deadline = (Get-Date).AddSeconds($HealthTimeoutSec)
$healthy = $false
while ((Get-Date) -lt $deadline) {
    $resp = wsl -d $Distro -- bash -lc 'curl -fsS http://localhost:8765/api/health 2>/dev/null' 2>&1
    if ($resp -match '"status":"ok"') {
        Write-OK "/api/health returned $resp"
        $healthy = $true
        break
    }
    Start-Sleep -Seconds 2
}
if (-not $healthy) {
    Write-Fail "/api/health did not return ok within ${HealthTimeoutSec}s. Check `docker compose logs roboclaw-web --since 2m`."
    exit 1
}

# ----- Summary -----
$elapsed = ((Get-Date) - $startedAt).TotalSeconds
Write-Host ""
Write-Host "=== RESUME PASS — $([int]$elapsed)s ===" -ForegroundColor Green
Write-Host "  USB:       $($attachExit -eq 0 ? 'all 7 devices accounted for' : 'partial — see attach output above')"
Write-Host "  Container: roboclaw-web Up (healthy)"
Write-Host "  Health:    /api/health ok"
Write-Host ""
Write-Host "Next: bind manifest (HUM-3 / HUM-4) once you're ready to drive the agent." -ForegroundColor White
