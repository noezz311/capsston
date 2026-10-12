"""Fail closed until legacy controller startup has been inventoried and disabled.

This checks known legacy services and processes; it cannot discover all arbitrary
controller names. The signed-off inventory is therefore required, including
non-systemd launch sources. No process is killed and no service is changed.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


UNIT_RE = re.compile(r"[A-Za-z0-9_.@:-]+\.service\Z")


def load_inventory(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("reviewed") is not True or data.get("external_startup_checked") is not True:
        raise ValueError("Legacy startup inventory is not reviewed; owner startup is blocked")
    units = data.get("services")
    patterns = data.get("process_patterns")
    if not isinstance(units, list) or not all(isinstance(x, str) and UNIT_RE.fullmatch(x) for x in units):
        raise ValueError("services must contain exact systemd .service names")
    if any(x.startswith("capstone-") for x in units):
        raise ValueError("The new capstone services cannot be listed as legacy services")
    if not isinstance(patterns, list) or not patterns or not all(isinstance(x, str) and x for x in patterns):
        raise ValueError("At least one legacy process pattern is required")
    for pattern in patterns:
        re.compile(pattern)
    return data


def check_services(units, run=subprocess.run):
    errors = []
    for unit in units:
        result = run(["systemctl", "show", unit, "--property=LoadState,ActiveState,UnitFileState"],
                     text=True, capture_output=True, check=False, timeout=10)
        props = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if result.returncode != 0:
            errors.append("Cannot inspect legacy unit: " + unit)
            continue
        if props.get("LoadState") == "not-found":
            errors.append("Inventory unit was not found; verify its exact name: " + unit)
            continue
        if props.get("ActiveState") not in ("inactive", "failed"):
            errors.append("Legacy unit is still active: " + unit)
        if props.get("UnitFileState") != "masked":
            errors.append("Legacy unit is not persistently masked: " + unit)
    return errors


def check_processes(patterns, proc_root=Path("/proc")):
    errors = []
    compiled = [re.compile(x) for x in patterns]
    for proc in proc_root.iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            errors.append("Cannot inspect process {} (proc visibility required)".format(proc.name))
            continue
        if any(pattern.search(command) for pattern in compiled):
            # Do not expose arbitrary process arguments: they can contain secrets.
            errors.append("Legacy controller process detected, PID=" + proc.name)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Startup guard must run on the Linux deployment host")
    try:
        inventory = load_inventory(args.inventory)
        errors = check_services(inventory["services"]) + check_processes(inventory["process_patterns"])
        if errors:
            raise ValueError("; ".join(errors))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("Capstone startup blocked: {}".format(exc), file=sys.stderr)
        return 1
    print("Legacy controller inventory and startup guard passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
