#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ROBOT_NAME="so101"
CALIBRATION_ID="so101_real"
SOURCE_PATH=""

die() {
  echo "error: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  scripts/prepare-native-calibration.sh [--robot <robot>] [--calibration-id <id>] [--source <file>]

Behavior:
  - Without --source, resolve the canonical RoboClaw calibration path and import from any
    supported legacy cache when available.
  - With --source, copy the provided calibration file into the canonical RoboClaw native path.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --robot)
      [ -n "${2:-}" ] || die "missing value for --robot"
      ROBOT_NAME="$2"
      shift 2
      ;;
    --calibration-id)
      [ -n "${2:-}" ] || die "missing value for --calibration-id"
      CALIBRATION_ID="$2"
      shift 2
      ;;
    --source)
      [ -n "${2:-}" ] || die "missing value for --source"
      SOURCE_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

PYTHON_BIN="$(command -v python3 || command -v python || true)"
[ -n "${PYTHON_BIN}" ] || die "python3 or python is required"

if [ -n "${SOURCE_PATH}" ] && [ ! -f "${SOURCE_PATH}" ]; then
  die "source calibration file '${SOURCE_PATH}' does not exist"
fi

cd "${REPO_ROOT}"

if [ -n "${SOURCE_PATH}" ]; then
  "${PYTHON_BIN}" - "${ROBOT_NAME}" "${CALIBRATION_ID}" "${SOURCE_PATH}" <<'PY'
from pathlib import Path
import shutil
import sys

from roboclaw.config.paths import get_robot_calibration_dir

robot_name, calibration_id, source_path = sys.argv[1:4]
source = Path(source_path).expanduser().resolve()
target = get_robot_calibration_dir(robot_name) / f"{calibration_id}.json"
target.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(source, target)
print(target)
PY
  exit 0
fi

"${PYTHON_BIN}" - "${ROBOT_NAME}" "${CALIBRATION_ID}" <<'PY'
from pathlib import Path
import sys

from roboclaw.config.paths import ensure_robot_calibration_file

robot_name, calibration_id = sys.argv[1:3]
target = ensure_robot_calibration_file(robot_name, calibration_id)
if not Path(target).exists():
    raise SystemExit(
        "error: no canonical calibration exists yet and no supported legacy calibration cache could be imported"
    )
print(target)
PY
