#!/usr/bin/env bash
set -e

# Values come from the generated runtime EnvironmentFile (systemd), or exported
# variables (manual run). Source scripts may reference unset variables, so enable
# nounset only after sourcing the selected ROS environment.
: "${CAPSTONE_PROJECT:?Explicit Linux project path is required}"
: "${CAPSTONE_PYTHON:?Explicit ROS-compatible Python executable is required}"
: "${CAPSTONE_CONFIG:?Config path is required}"
: "${CAPSTONE_ROS_SETUP:?Verified ROS setup.bash path is required}"
: "${CAPSTONE_WORKSPACE_SETUP:?Built workspace setup.bash path is required}"
: "${CAPSTONE_ROS_VERSION:?Verified ROS major version (1 or 2) is required}"

for path in "$CAPSTONE_ROS_SETUP" "$CAPSTONE_WORKSPACE_SETUP" "$CAPSTONE_CONFIG"; do
    test -r "$path" || { printf 'Required file is not readable: %s\n' "$path" >&2; exit 1; }
done
test -x "$CAPSTONE_PYTHON" || { printf 'Python executable unavailable\n' >&2; exit 1; }
source "$CAPSTONE_ROS_SETUP"
source "$CAPSTONE_WORKSPACE_SETUP"
set -u
if [[ "${ROS_VERSION:-}" != "$CAPSTONE_ROS_VERSION" ]]; then
    printf 'Sourced ROS_VERSION does not match explicit deployment selection\n' >&2
    exit 1
fi
case "${1:-}" in
    hardware-node|control-server|monitor-server) role="$1" ;;
    *) printf 'Expected hardware-node, control-server or monitor-server\n' >&2; exit 2 ;;
esac
if [[ "$role" == hardware-node ]]; then
    : "${CAPSTONE_LEGACY_INVENTORY:?Reviewed inventory is required before owner startup}"
    "$CAPSTONE_PYTHON" "$CAPSTONE_PROJECT/deployment/check_startup.py" --inventory "$CAPSTONE_LEGACY_INVENTORY"
fi
cd "$CAPSTONE_PROJECT"
exec "$CAPSTONE_PYTHON" -m capstone.cli "$role" --config "$CAPSTONE_CONFIG"
