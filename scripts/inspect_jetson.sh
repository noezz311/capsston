#!/usr/bin/env bash
# Read-only inventory. Run on the SSH destination, not the Windows development PC.
set -u
printf '\n--- Kernel/architecture ---\n'
uname -a
printf '\n--- OS release ---\n'
cat /etc/os-release
printf '\n--- Board model ---\n'
if test -r /proc/device-tree/model; then tr -d '\000' < /proc/device-tree/model; printf '\n'; else printf 'No device-tree model\n'; fi
printf '\n--- L4T release ---\n'
if test -r /etc/nv_tegra_release; then cat /etc/nv_tegra_release; else printf 'No NVIDIA L4T release file\n'; fi
printf '\n--- Installed JetPack/L4T/BlueZ packages ---\n'
dpkg-query -W nvidia-jetpack nvidia-l4t-core bluez 2>/dev/null || true
printf '\n--- Python and Bluetooth ---\n'
python3 --version
bluetoothctl --version 2>/dev/null || true
bluetoothctl list 2>/dev/null || true
printf '\n--- Installed ROS setups (selection is still explicit) ---\n'
find /opt/ros -maxdepth 2 -name setup.bash -print 2>/dev/null || true
printf '\n--- Sourced ROS environment ---\n'
printf 'ROS_VERSION=%s ROS_DISTRO=%s\n' "${ROS_VERSION:-UNSET}" "${ROS_DISTRO:-UNSET}"
printf '\n--- Candidate legacy system units (review full system inventory too) ---\n'
systemctl list-unit-files --no-pager 2>/dev/null | grep -Ei 'map|monitor|gpio|door|capstone|robot|main1' || true
printf '\n--- Device permissions ---\n'
id
ls -l /dev/gpiochip* /sys/class/gpio/export /sys/class/gpio/unexport 2>/dev/null || true
