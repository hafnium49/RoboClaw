#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

INSTANCE_NAME="${INSTANCE_NAME:-matrix-so101-acceptance}"
SCRIPT_DIR="$(pwd)/scripts/docker"

# shellcheck source=../scripts/docker/common.sh
source "${SCRIPT_DIR}/common.sh"

echo "=== Building immutable ROS2 validation matrix ==="
"${SCRIPT_DIR}/matrix.sh" build "${INSTANCE_NAME}"

while IFS= read -r profile; do
  [ -n "${profile}" ] || continue
  SESSION_ID="cli:accept-${INSTANCE_NAME}-${profile}"
  SESSION_FILE="$(instance_dir "${INSTANCE_NAME}" "${profile}")/workspace/sessions/$(printf '%s' "${SESSION_ID}" | tr ':' '_').jsonl"

  echo ""
  echo "=== ${profile}: running SO101 acceptance flow ==="
  "${SCRIPT_DIR}/run-task.sh" --profile "${profile}" "${INSTANCE_NAME}" \
    agent -m "I want to connect a real robot" --session "${SESSION_ID}" --no-markdown
  "${SCRIPT_DIR}/run-task.sh" --profile "${profile}" "${INSTANCE_NAME}" \
    agent -m "SO101" --session "${SESSION_ID}" --no-markdown
  "${SCRIPT_DIR}/run-task.sh" --profile "${profile}" "${INSTANCE_NAME}" \
    agent -m "connected" --session "${SESSION_ID}" --no-markdown
  OPEN_OUTPUT="$("${SCRIPT_DIR}/run-task.sh" --profile "${profile}" "${INSTANCE_NAME}" \
    agent -m "open the gripper" --session "${SESSION_ID}" --no-markdown)"
  printf '%s\n' "${OPEN_OUTPUT}"
  grep -q "Primitive gripper_open completed" <<< "${OPEN_OUTPUT}"

  CLOSE_OUTPUT="$("${SCRIPT_DIR}/run-task.sh" --profile "${profile}" "${INSTANCE_NAME}" \
    agent -m "close the gripper" --session "${SESSION_ID}" --no-markdown)"
  printf '%s\n' "${CLOSE_OUTPUT}"
  grep -q "Primitive gripper_close completed" <<< "${CLOSE_OUTPUT}"

  echo "=== ${profile}: validating session metadata ==="
  grep -q "/dev/serial/by-id/" "${SESSION_FILE}"
  if grep -Eq "/dev/ttyACM|/dev/ttyUSB" "${SESSION_FILE}"; then
    echo "error: tty device path leaked into session metadata for ${profile}" >&2
    exit 1
  fi
done < <(split_profiles_csv "${DEFAULT_MATRIX_PROFILES}")

echo ""
echo "=== Matrix SO101 acceptance completed ==="
