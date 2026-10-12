#!/usr/bin/env bash
set -e
cd /home/lisa/capsston
for role in monitor map; do
    if systemctl --user is-active --quiet "capstone-$role.service"; then
        printf '%s is already active\n' "capstone-$role"
        continue
    fi
    systemd-run --user --unit="capstone-$role" \
        --property=WorkingDirectory=/home/lisa/capsston \
        --property=EnvironmentFile=/home/lisa/capsston/runtime.env \
        --property=Restart=on-failure --property=RestartSec=5 \
        --property=KillSignal=SIGINT --property=TimeoutStopSec=40 \
        --property=NoNewPrivileges=yes --property=UMask=0077 \
        /home/lisa/capsston/.venv/bin/python -u \
        "/home/lisa/capsston/$role-server.py"
done
