"""Render reviewable systemd units; never install or start them automatically."""

import argparse
import importlib.util
from pathlib import Path, PurePosixPath
import re
import sys


def linux_path(value):
    if not PurePosixPath(value).is_absolute() or any(c in value for c in "\n\r\0%\"\\$"):
        raise argparse.ArgumentTypeError("Use an absolute Linux path without shell/systemd expansion characters")
    return value


def account(value):
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*[$]?", value):
        raise argparse.ArgumentTypeError("Use an existing explicit Linux account/group name")
    return value


def quoted(value):
    return '"' + value + '"'


def render(args, legacy):
    project = args.project.rstrip("/")
    runtime_env = str(PurePosixPath(args.runtime_env))
    environment = {
        "CAPSTONE_PROJECT": project,
        "CAPSTONE_PYTHON": args.python,
        "CAPSTONE_CONFIG": args.config,
        "CAPSTONE_ROS_SETUP": args.ros_setup,
        "CAPSTONE_WORKSPACE_SETUP": args.workspace_setup,
        "CAPSTONE_ROS_VERSION": args.ros_version,
        "CAPSTONE_LEGACY_INVENTORY": args.inventory_path,
        "PYTHONUNBUFFERED": "1",
    }
    files = {"capstone-runtime.env": "\n".join(k + "=" + quoted(v) for k, v in environment.items()) + "\n"}
    services = (("hardware", "hardware-node"), ("control", "control-server"), ("monitor", "monitor-server"))
    for name, role in services:
        dependencies = "After=network-online.target\nWants=network-online.target\n"
        extra = ""
        if name == "hardware":
            dependencies += "After=bluetooth.service\nWants=bluetooth.service\n"
            if legacy["services"]:
                dependencies += "Conflicts=" + " ".join(legacy["services"]) + "\n"
            extra += "ExecStartPre={} {} --inventory {}\n".format(
                quoted(args.python), quoted(project + "/deployment/check_startup.py"), quoted(args.inventory_path))
            if args.supplementary_group:
                extra += "SupplementaryGroups=" + " ".join(args.supplementary_group) + "\n"
            extra += "RuntimeDirectory=capstone\nRuntimeDirectoryMode=0750\nRuntimeDirectoryPreserve=yes\n"
        else:
            # Web services stay available during an owner restart and report stale/unavailable state.
            dependencies += "After=capstone-hardware.service\nWants=capstone-hardware.service\n"
        files["capstone-" + name + ".service"] = (
            "# Generated: inspect paths, permissions and legacy inventory before installation.\n"
            "[Unit]\nDescription=Capstone " + name + " service\n" + dependencies +
            "PartOf=capstone.target\nStartLimitIntervalSec=60\nStartLimitBurst=5\n\n"
            "[Service]\nType=simple\nUser=" + args.user + "\nGroup=" + args.group + "\n" +
            "WorkingDirectory=" + quoted(project) + "\nEnvironmentFile=" + quoted(runtime_env) + "\n" +
            "EnvironmentFile=" + quoted(args.secret_env) + "\n" + extra +
            "ExecStart=/bin/bash " + quoted(project + "/deployment/run-service.sh") + " " + role + "\n" +
            "Restart=on-failure\nRestartSec=3\nKillSignal=SIGINT\nTimeoutStopSec=45\n" +
            "NoNewPrivileges=true\nProtectSystem=full\nUMask=0077\n" +
            "StandardOutput=journal\nStandardError=journal\n\n[Install]\nWantedBy=capstone.target\n"
        )
    files["capstone.target"] = (
        "[Unit]\nDescription=Capstone ROS hardware and HTTP services\n"
        "Wants=capstone-hardware.service capstone-control.service capstone-monitor.service\n"
        "After=network-online.target\n\n[Install]\nWantedBy=multi-user.target\n"
    )
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("project", "python", "config", "ros-setup", "workspace-setup", "runtime-env", "secret-env", "inventory-path"):
        parser.add_argument("--" + arg, required=True, type=linux_path)
    for arg in ("user", "group"):
        parser.add_argument("--" + arg, required=True, type=account)
    parser.add_argument("--ros-version", required=True, choices=("1", "2"))
    parser.add_argument("--supplementary-group", action="append", default=[], type=account)
    parser.add_argument("--inventory", required=True, type=Path, help="Reviewed local inventory JSON to validate")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("check_startup", Path(__file__).resolve().parents[1] / "deployment" / "check_startup.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    try:
        legacy = guard.load_inventory(args.inventory)
        files = render(args, legacy)
        args.output.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            with (args.output / name).open("w", encoding="utf-8", newline="\n") as output:
                output.write(content)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print("Rendered {} files in {}; no host services changed".format(len(files), args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
