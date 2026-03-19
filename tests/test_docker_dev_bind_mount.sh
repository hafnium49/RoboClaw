#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

INSTANCE_NAME="${INSTANCE_NAME:-docker-dev-bind-mount}"
PROFILE="${PROFILE:-ubuntu2404-ros2}"
SCRIPT_DIR="$(pwd)/scripts/docker"
PROBE_MODULE="roboclaw/_dev_bind_mount_probe.py"
PROBE_CACHE_DIR="roboclaw/__pycache__"
FIRST_MARKER="bind-mount-first"
SECOND_MARKER="bind-mount-second"

# shellcheck source=../scripts/docker/common.sh
source "${SCRIPT_DIR}/common.sh"

cleanup() {
  rm -f "${PROBE_MODULE}"
  rm -f "${PROBE_CACHE_DIR}"/_dev_bind_mount_probe*.pyc 2>/dev/null || true
}
trap cleanup EXIT

cat > "${PROBE_MODULE}" <<EOF
VALUE = "${FIRST_MARKER}"
EOF

echo "=== Starting Docker dev container ==="
"${SCRIPT_DIR}/start-dev.sh" --profile "${PROFILE}" "${INSTANCE_NAME}" >/dev/null
CONTAINER_NAME="$(dev_container_name "${INSTANCE_NAME}" "${PROFILE}")"

echo "=== Verifying first marker through bind-mounted source ==="
FIRST_OUTPUT="$(docker exec "${CONTAINER_NAME}" python - <<'PY'
import importlib
module = importlib.import_module("roboclaw._dev_bind_mount_probe")
print(module.VALUE)
PY
)"
printf '%s\n' "${FIRST_OUTPUT}"
[ "${FIRST_OUTPUT}" = "${FIRST_MARKER}" ]

cat > "${PROBE_MODULE}" <<EOF
VALUE = "${SECOND_MARKER}"
EOF

echo "=== Verifying host edit is visible without rebuild ==="
SECOND_OUTPUT="$(docker exec "${CONTAINER_NAME}" python - <<'PY'
import importlib
module = importlib.import_module("roboclaw._dev_bind_mount_probe")
print(module.VALUE)
PY
)"
printf '%s\n' "${SECOND_OUTPUT}"
[ "${SECOND_OUTPUT}" = "${SECOND_MARKER}" ]

echo "=== Docker dev bind-mount check passed ==="
