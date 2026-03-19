#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

SESSION_ID="${SESSION_ID:-cli:native-so101-acceptance}"
SCRIPT_DIR="$(pwd)/scripts"
SESSION_FILE="${HOME}/.roboclaw/workspace/sessions/$(printf '%s' "${SESSION_ID}" | tr ':' '_').jsonl"
CALIBRATION_SOURCE="${CALIBRATION_SOURCE:-}"

echo "=== Preparing native canonical calibration ==="
if [ -n "${CALIBRATION_SOURCE}" ]; then
  "${SCRIPT_DIR}/prepare-native-calibration.sh" \
    --robot so101 \
    --calibration-id so101_real \
    --source "${CALIBRATION_SOURCE}"
else
  "${SCRIPT_DIR}/prepare-native-calibration.sh" --robot so101 --calibration-id so101_real
fi

echo "=== Native hello smoke ==="
roboclaw agent -m "hello" --session "${SESSION_ID}" --no-markdown

echo "=== Native SO101 acceptance flow ==="
roboclaw agent -m "I want to connect a real robot" --session "${SESSION_ID}" --no-markdown
roboclaw agent -m "SO101" --session "${SESSION_ID}" --no-markdown
roboclaw agent -m "connected" --session "${SESSION_ID}" --no-markdown
OPEN_OUTPUT="$(roboclaw agent -m "open the gripper" --session "${SESSION_ID}" --no-markdown)"
printf '%s\n' "${OPEN_OUTPUT}"
grep -q "Primitive gripper_open completed" <<< "${OPEN_OUTPUT}"

CLOSE_OUTPUT="$(roboclaw agent -m "close the gripper" --session "${SESSION_ID}" --no-markdown)"
printf '%s\n' "${CLOSE_OUTPUT}"
grep -q "Primitive gripper_close completed" <<< "${CLOSE_OUTPUT}"

echo "=== Validating native session metadata ==="
grep -q "/dev/serial/by-id/" "${SESSION_FILE}"
if grep -Eq "/dev/ttyACM|/dev/ttyUSB" "${SESSION_FILE}"; then
  echo "error: tty device path leaked into native session metadata" >&2
  exit 1
fi

echo "=== Native SO101 acceptance completed ==="
