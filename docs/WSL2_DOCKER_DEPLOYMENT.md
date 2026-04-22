# WSL2 + Docker Deployment (SO-101 Bimanual)

This guide documents the local deployment of RoboClaw on Windows 11 with WSL2,
isolated from any other WSL2 project that may already own the SO-101 hardware.
It corresponds to the committed changes in `Dockerfile`, `docker-compose.yml`,
and `scripts/attach_usb_roboclaw.ps1`.

Reach for this doc when:
- You have a Windows 11 host, SO-101 leader+follower arms on CH343 USB-serial,
  and at least one UVC camera.
- You want RoboClaw to run in a Docker container without disturbing an unrelated
  WSL2 project that already uses `usbipd-win` passthrough.
- You want the FastAPI dashboard served by the same container that runs the
  agent and the embodied subsystem — one port, one container, one volume.

It is **not** a replacement for `INSTALLATION.md` (native uv path) or
`DOCKERINSTALLATION.md` (minimal stateless Docker path). It is a third,
hardware-grade deployment mode.

---

## 1. Architecture at a glance

```
+-----------------------------------------+        +-----------------------+
|  Windows 11                             |        |  WSL2 distro "Ubuntu" |
|  -----------                            |        |  (existing, untouched)|
|  usbipd-win  <-- SO-101 x4 + UVC cam    |        |  used by unrelated    |
|       |                                 |        |  so101-rl-deploy      |
|       | (usbipd attach --wsl            |        +-----------------------+
|       |   Ubuntu-roboclaw --auto-attach)
|       v
|  +-----------------------------------+  |        +-----------------------+
|  |  WSL2 distro "Ubuntu-roboclaw"    |  |        |  Windows browser      |
|  |  (dedicated, created by operator) |  |        |  http://localhost:8765|
|  |                                   |  |        +-----------^-----------+
|  |  /dev/ttyACM0..3  /dev/video0     |  |                    |
|  |  udev -> /dev/serial/by-id/*      |  |        port 8765 + 1455 forwarded
|  |                                   |  |
|  |  Docker Engine (NOT Docker Desktop)
|  |    |                              |  |
|  |    v                              |  |
|  |  Container: roboclaw-web          |  |
|  |    - roboclaw web start :8765     |  |
|  |    - FastAPI + React SPA          |  |
|  |    - embodied subsystem           |  |
|  |    - openai-codex provider        |  |
|  |    volumes:                       |  |
|  |      /root/.roboclaw  <- ext4     |  |
|  |      /root/.cache/huggingface     |  |
|  +-----------------------------------+  |
+-----------------------------------------+
```

Key design choices and why they exist:

| Choice | Reason |
|--------|--------|
| Dedicated WSL2 distro (`Ubuntu-roboclaw`), not `docker-desktop` | Docker Desktop's internal LinuxKit VM lacks `vhci-hcd`/`usbip-core` kernel modules and udev, so `usbipd attach --wsl docker-desktop` fails and `/dev/serial/by-id/` stays empty. A full Ubuntu distro has both. |
| Docker **Engine** inside that distro, not Docker Desktop | Removes the Docker Desktop VM hop entirely. Containers run under the same kernel that `usbipd` attaches devices to, so `--device /dev/ttyACMx` works. |
| Multi-stage Dockerfile with **editable** Python install | `roboclaw/http/server.py:297` resolves `ui_dist = Path(__file__).parent.parent.parent / "ui" / "dist"`. Under a system install into `site-packages` this resolves to a non-existent path and the UI silently 404s. `uv pip install -e .` keeps the import root at `/app/roboclaw/…` so `/app/ui/dist/` is found. |
| `-p 127.0.0.1:1455:1455` | `roboclaw/providers/openai_codex_provider.py` runs an OAuth callback server on `localhost:1455` inside the container; the redirect must reach that port from the Windows browser. |
| Volume at `/home/hafnium/.roboclaw` on ext4 (inside the distro) | DrvFs (`/mnt/c/…`) is 5–20× slower for fsync-heavy workloads and mangles `0600` perms on the OAuth token. |
| Calibration via `docker compose exec -it`, not the browser | Calibration uses `termios` raw mode (`roboclaw/embodied/toolkit/tty.py`); the detached `web start` container has no PTY for the browser code path. CLI `exec -it` has a PTY. |
| Single container per volume | The cross-process flock in `roboclaw/embodied/embodiment/lock.py` is safe with a single writer; running two containers against the same volume is not supported. |

Full review rationale lives in `/home/hafnium/.claude/plans/let-s-deploy-roboclaw-locally-serene-finch.md`.

---

## 2. Prerequisites

- Windows 11 with WSL2 enabled (`wsl --install` if starting fresh).
- `usbipd-win` installed: `winget install usbipd`. Verify `usbipd --version`.
- An elevated PowerShell window available when binding USB devices.
- The SO-101 arms + camera physically connected and visible via
  `usbipd list` on Windows. You should see five shared devices: four
  CH343 serials (`idVendor=0x1a86`) and at least one UVC camera.

---

## 3. Create the dedicated WSL2 distro

Run in an **admin PowerShell** on Windows:

```powershell
$dl = "$env:USERPROFILE\wsl\ubuntu-roboclaw"
New-Item -ItemType Directory -Force -Path $dl | Out-Null

Invoke-WebRequest `
  -Uri https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-24.04-lts.rootfs.tar.gz `
  -OutFile "$dl\rootfs.tar.gz"

wsl --import Ubuntu-roboclaw "$dl" "$dl\rootfs.tar.gz" --version 2

# Create a non-root user named hafnium (swap in your own login)
wsl -d Ubuntu-roboclaw -- bash -c `
  "adduser --disabled-password --gecos '' hafnium && usermod -aG sudo hafnium && echo 'hafnium ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/hafnium"

wsl -d Ubuntu-roboclaw -- bash -c "printf '[user]\ndefault=hafnium\n[boot]\nsystemd=true\n' > /etc/wsl.conf"

wsl --terminate Ubuntu-roboclaw
```

`Ubuntu-roboclaw` does **not** become the default WSL distro. Always invoke it
explicitly with `wsl -d Ubuntu-roboclaw`.

---

## 4. Install Docker Engine inside `Ubuntu-roboclaw`

```bash
wsl -d Ubuntu-roboclaw
sudo apt update
sudo apt install -y ca-certificates curl gnupg git usbutils
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

Restart the distro so the `docker` group membership takes effect:

```powershell
wsl --terminate Ubuntu-roboclaw
wsl -d Ubuntu-roboclaw
docker run --rm hello-world
```

Verify `systemctl status docker` shows `active (running)`. If not, confirm
`[boot] systemd=true` is present in `/etc/wsl.conf` and restart the distro.

---

## 5. Clone the repository inside the distro

```bash
wsl -d Ubuntu-roboclaw
git clone --recurse-submodules https://github.com/hafnium49/RoboClaw.git ~/RoboClaw
cd ~/RoboClaw
git remote add upstream https://github.com/MINT-SJTU/RoboClaw.git
```

The embodied engine lives at `roboclaw/embodied/engine` as a submodule. If you
cloned without `--recurse-submodules`, run `git submodule update --init --recursive`.

---

## 6. Build the image

```bash
cd ~/RoboClaw
docker compose build roboclaw-web
```

The build produces three stages:
1. `node:20-slim` builds `ui/dist/` (React + Vite).
2. `node:20-slim` builds `bridge/dist/` (WhatsApp Baileys bridge).
3. `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` installs the Python
   package in editable mode and copies the two `dist/` trees into place.

Expected final image size: ~600–700 MB.

---

## 7. First-run initialization (no hardware required)

Scaffold the config + workspace on the ext4 filesystem:

```bash
docker compose run --rm roboclaw-web onboard
```

This populates `/home/hafnium/.roboclaw/` (bind-mounted into the container at
`/root/.roboclaw`) with `config.json` and
`workspace/{AGENTS,SOUL,TOOLS,USER,HEARTBEAT}.md` plus `memory/MEMORY.md`.

---

## 8. Provider login (openai-codex OAuth)

Port `1455` is exposed by `docker-compose.yml`. Run the login interactively:

```bash
docker compose run --rm roboclaw-web provider login openai-codex
```

The provider opens an `HTTPServer` on `localhost:1455` **inside the container**;
Docker forwards that to Windows `127.0.0.1:1455`; your Windows browser hits the
redirect and completes the flow. The token lands in `~/.roboclaw/` with proper
`0600` perms.

Edit `~/.roboclaw/config.json` afterwards to set
`agents.defaults.model` to the Codex model you want (see
`roboclaw/providers/openai_codex_provider.py` for accepted identifiers).

Smoke-test the provider wiring:

```bash
docker compose run --rm roboclaw-web agent -m "hello"
```

---

## 9. Route USB into `Ubuntu-roboclaw`

Do **not** modify any existing `attach_usb_wsl.ps1` — that one routes the same
BUSIDs to your other project's distro. Instead, use the committed script:

```powershell
# From an elevated PowerShell on Windows:
cd <repo>\scripts
.\attach_usb_roboclaw.ps1
```

What the script does:
1. Verifies it is running elevated.
2. Confirms `Ubuntu-roboclaw` exists.
3. Detaches each BUSID first (so we never collide with a prior attachment to
   another distro).
4. `usbipd bind --busid <b> --force` — makes the bind survive Windows reboots.
5. Spawns one hidden `usbipd attach --wsl Ubuntu-roboclaw --busid <b>
   --auto-attach` per BUSID. These processes stay alive in the background so
   devices reattach automatically on replug.
6. Verifies by listing `/dev/ttyACM*`, `/dev/video*`, and
   `/dev/serial/by-id/` inside `Ubuntu-roboclaw`.

Flags:

| Flag | Purpose |
|------|---------|
| `-Distro <name>` | Override target distro (default `Ubuntu-roboclaw`). |
| `-BusIds <array>` | Override BUSIDs (default `4-3, 4-4, 5-1, 5-3, 5-4`). Re-verify yours with `usbipd list`. |
| `-Detach` | Reverse direction — detach all BUSIDs from every distro. Use before handing the hardware back to another project. |

To make auto-attach persist across Windows reboots, register the script as a
Task Scheduler entry triggered **At log on**, running hidden.

---

## 10. Start the runtime

```bash
wsl -d Ubuntu-roboclaw
cd ~/RoboClaw
docker compose up -d roboclaw-web
docker compose ps
docker compose logs -f roboclaw-web
```

Open `http://localhost:8765/` in a Windows browser. The single port serves
both the React dashboard (static files from `/app/ui/dist/`) and the
FastAPI + WebSocket API — same-origin, no CORS.

Health:

```bash
curl -fsS http://localhost:8765/api/health
docker compose exec roboclaw-web roboclaw status
```

---

## 11. Embodied onboarding (bimanual SO-101)

### 11.1 Calibrate arms (CLI only)

```bash
docker compose exec -it roboclaw-web roboclaw agent
# Ask the agent: "List detected arms and cameras, then calibrate each SO-101 arm."
```

Calibration must be driven from `docker compose exec -it` because the
termios raw-mode path in `roboclaw/embodied/toolkit/tty.py` needs a PTY. The
browser-based calibration panel will hang in this deployment — that is a known
constraint of the detached `web start` container.

### 11.2 Bind arms and cameras

After calibration, use the dashboard's Setup panel (or the agent with embodied
tools) to build the manifest:

- 2× `so101_leader` — `role=leader`, `side ∈ {left, right}`
- 2× `so101_follower` — `role=follower`, `side ∈ {left, right}`
- 1–3× cameras, each labelled with `side`

Bind arms by their stable `/dev/serial/by-id/usb-...` paths (visible in the
script's verification output). `ttyACM` indices reshuffle on replug; `by-id`
does not.

### 11.3 Teleop / record / replay / infer (dashboard)

Once bound, those four workflows run fine from the browser dashboard — they do
not need a PTY. Bimanual mode activates automatically:
`roboclaw/embodied/command/builder.py:22-25` maps `"so101"` →
`("bi_so_follower", "bi_so_leader")` when `arms=""`.

---

## 12. Operating procedures

### 12.1 Switching the robot between projects

Only one WSL distro can own a given USB device at a time, so switching projects
is explicit:

```powershell
# Give the robot to RoboClaw:
.\scripts\attach_usb_roboclaw.ps1

# Give it back to the other project (example):
.\scripts\attach_usb_roboclaw.ps1 -Detach
.\<path-to-other-project>\attach_usb_wsl.ps1
```

Stop the RoboClaw container before detaching, to avoid mid-op failures:

```bash
docker compose stop roboclaw-web
```

### 12.2 Persistent auto-attach across reboots

Register `attach_usb_roboclaw.ps1` as a Windows Task Scheduler task:
- Trigger: **At log on of any user**.
- Action: `powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "<full path>\attach_usb_roboclaw.ps1"`.
- Run with highest privileges.

### 12.3 Data persistence

- `/home/hafnium/.roboclaw/` — config, workspace, memory, session state.
- Named volume `hf_cache` — LeRobot dataset cache at
  `~/.cache/huggingface/lerobot` (see `roboclaw/embodied/command/builder.py:30`).
  Recorded episodes live here; do not delete the volume unless you intend to
  lose them.

Back up with:

```bash
tar czf /tmp/roboclaw-backup-$(date +%F).tgz /home/hafnium/.roboclaw
docker run --rm -v hf_cache:/data -v /tmp:/out alpine \
  tar czf /out/hf_cache-$(date +%F).tgz -C /data .
```

### 12.4 Logs

JSON logs rotate at 10 MB × 3 files per service:

```bash
docker compose logs -f roboclaw-web
docker compose logs --tail 500 roboclaw-web
```

### 12.5 Updating to a newer RoboClaw

```bash
cd ~/RoboClaw
git pull --rebase upstream main
docker compose build roboclaw-web
docker compose up -d roboclaw-web
```

A full image rebuild is required for UI changes because `ui/dist/` is baked in.
There is no in-container hot reload — the UI is intentionally static in this
deployment mode.

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Dashboard at `http://localhost:8765/` returns HTTP 404 for assets | Non-editable install; `ui/dist/` path mismatch | Rebuild image; confirm Dockerfile uses `uv pip install --system --no-cache -e .`. |
| `roboclaw provider login openai-codex` hangs; browser can't open callback | Port 1455 not published | Confirm `docker-compose.yml` maps `127.0.0.1:1455:1455` on `roboclaw-web`. |
| `/dev/ttyACM*` missing inside the distro | usbipd still attached elsewhere; or CH343 replugged after Windows reboot | Re-run `attach_usb_roboclaw.ps1`. Confirm BUSIDs match `usbipd list`. |
| `/dev/serial/by-id/` empty | udev not running in distro | Happens in minimal distros; `Ubuntu-roboclaw` from the 24.04 cloud rootfs has udev. Verify with `systemctl status systemd-udevd`. |
| Teleop at 30 Hz drops frames intermittently | usbipd-over-TCP jitter through the Windows scheduler | Drop to 20 Hz. Close heavy Windows workloads. If persistent, consider moving the robot to a native Linux host. |
| Camera fails to enumerate at >720p | UVC isochronous endpoints over usbipd | Force MJPEG at 720p30; the scanner already sets `CAP_PROP_FOURCC=MJPG` in `roboclaw/embodied/embodiment/hardware/scan.py:503`. Using more than one UVC camera through usbipd is unreliable. |
| Browser-driven calibration hangs | No PTY in the detached container | Calibrate via `docker compose exec -it roboclaw-web roboclaw agent`. |
| `docker compose up` complains about cgroup rule 188/189 | Older kernel without those majors | Harmless in practice; remove the two lines if your runtime refuses them. The plan keeps them as defensive entries for CH343 fallback modes. |

---

## 14. Explicit non-goals of this deployment

- Running two containers against the same `~/.roboclaw` volume (flock
  semantics over a bind mount are not verified for multi-writer).
- Enabling Docker Desktop's WSL integration with the primary `Ubuntu` distro
  (would re-couple the two projects).
- Training runs on the same host — teleop + record are the first-pass goal;
  training can move to a dedicated GPU host consuming datasets from
  `hf_cache`.
- Exposing `8765` beyond `127.0.0.1`. If you need LAN access, put a reverse
  proxy with authentication in front of the container.

---

## 15. Referenced repo files

| File | What it anchors |
|------|-----------------|
| `Dockerfile` | Multi-stage build, editable install, exposed ports. |
| `docker-compose.yml` | `roboclaw-web` service, devices, cgroup rules, volumes, healthcheck. |
| `scripts/attach_usb_roboclaw.ps1` | Windows-side USB routing to `Ubuntu-roboclaw`. |
| `roboclaw/http/server.py:297` | UI path resolution; relies on editable install. |
| `roboclaw/providers/openai_codex_provider.py` | OAuth callback on port 1455. |
| `roboclaw/embodied/toolkit/tty.py` | Termios raw-mode handoff (PTY-only). |
| `roboclaw/embodied/embodiment/lock.py` | Cross-process embodiment lock. |
| `roboclaw/embodied/embodiment/hardware/scan.py` | `/dev/serial/by-id/` discovery, UVC fourcc settings. |
| `roboclaw/embodied/command/builder.py:22-25` | Bimanual SO-101 preset `_BIMANUAL["so101"]`. |
| `docs/INSTALLATION.md` | Native uv path (alternative to this doc). |
| `docs/DOCKERINSTALLATION.md` | Minimal stateless Docker path (alternative to this doc). |
