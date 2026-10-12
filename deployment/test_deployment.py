"""Deployment safety checks that do not need Linux/systemd or real hardware."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_module("guard", ROOT / "deployment/check_startup.py")
renderer = load_module("renderer", ROOT / "scripts/render_systemd.py")


class DeploymentTests(unittest.TestCase):
    def test_unknown_inventory_cannot_start(self):
        with self.assertRaisesRegex(ValueError, "not reviewed"):
            guard.load_inventory(ROOT / "deployment/legacy-inventory.example.json")

    def test_unit_injection_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.json"
            inventory.write_text(json.dumps({"reviewed": True, "external_startup_checked": True,
                                            "services": ["old.service\nExecStart=bad"],
                                            "process_patterns": ["main1.py"]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact systemd"):
                guard.load_inventory(inventory)

    def test_masking_and_stop_both_required(self):
        def result(text):
            return lambda *a, **kw: subprocess.CompletedProcess(a, 0, text, "")
        self.assertEqual(guard.check_services(["old.service"], result("LoadState=masked\nActiveState=inactive\nUnitFileState=masked\n")), [])
        self.assertIn("still active", " ".join(guard.check_services(["old.service"], result("LoadState=masked\nActiveState=active\nUnitFileState=masked\n"))))
        self.assertIn("not persistently masked", " ".join(guard.check_services(["old.service"], result("LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n"))))

    def test_legacy_process_detected_without_exposing_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "12345"
            proc.mkdir()
            (proc / "cmdline").write_bytes(b"python3\x00/old/main1.py\x00--secret=never-print\x00")
            errors = guard.check_processes([r"(?:^|[/\s])main1\.py(?:\s|$)"], Path(tmp))
            self.assertEqual(errors, ["Legacy controller process detected, PID=12345"])

    def test_windows_relative_and_expandable_paths_rejected(self):
        for path in ("C:/project", "relative", "/tmp/%n", "/tmp/$USER", "/tmp/one\ntwo"):
            with self.subTest(path=path), self.assertRaises(argparse.ArgumentTypeError):
                renderer.linux_path(path)
        self.assertEqual(renderer.linux_path("/srv/my project"), "/srv/my project")

    def test_rendered_services_have_explicit_runtime_and_legacy_guards(self):
        args = argparse.Namespace(project="/srv/my project", python="/srv/venv/bin/python",
                                  config="/srv/config.json", ros_setup="/verified/ros/setup.bash",
                                  workspace_setup="/verified/ws/setup.bash", runtime_env="/srv/runtime.env",
                                  secret_env="/srv/secrets.env", inventory_path="/srv/inventory.json",
                                  ros_version="2", user="robot", group="robot", supplementary_group=["gpio"])
        files = renderer.render(args, {"services": ["old-map.service"]})
        self.assertEqual(len(files), 5)
        owner = files["capstone-hardware.service"]
        self.assertIn("Conflicts=old-map.service", owner)
        self.assertIn("check_startup.py", owner)
        self.assertIn("RuntimeDirectoryPreserve=yes", owner)
        self.assertIn("User=robot", owner)
        self.assertIn('WorkingDirectory="/srv/my project"', owner)
        self.assertIn("hardware-node", owner)
        self.assertNotIn("SupplementaryGroups", files["capstone-control.service"])
        self.assertNotIn("/opt/ros/humble", "".join(files.values()))


if __name__ == "__main__":
    unittest.main()
