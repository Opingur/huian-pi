from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from teaching_console.services.model_deployment_service import (
    DeploymentError,
    DeploymentSettings,
    ModelDeploymentService,
    validate_candidate_name,
)


class _Runner:
    def __init__(self, results: list[tuple[int, str, str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.results = list(results or [])

    def __call__(self, args, **_kwargs):
        self.calls.append(list(args))
        code, stdout, stderr = self.results.pop(0) if self.results else (0, "", "")
        return subprocess.CompletedProcess(args, code, stdout, stderr)


class ModelDeploymentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = DeploymentSettings()

    def test_default_target_is_the_requested_pi_project(self) -> None:
        self.assertEqual(self.settings.ssh_alias, "huian-pi")
        self.assertEqual(self.settings.remote_project_root, "/home/x/Huian_YOLO")

    def test_candidate_name_can_never_replace_baseline(self) -> None:
        with self.assertRaisesRegex(ValueError, "禁止覆盖"):
            validate_candidate_name("yolov8n.pt")
        with self.assertRaises(ValueError):
            validate_candidate_name("../other.pt")
        self.assertEqual(validate_candidate_name("huian_person_v1.pt"), "huian_person_v1.pt")

    def test_preflight_checks_ssh_project_config_and_models(self) -> None:
        runner = _Runner()
        ModelDeploymentService(command_runner=runner).check_ssh()
        self.assertEqual(runner.calls[0][:2], ["ssh", "huian-pi"])
        remote = runner.calls[0][2]
        self.assertIn("/home/x/Huian_YOLO", remote)
        self.assertIn("rpi_app/config.json", remote)
        self.assertIn("models", remote)

    def test_deploy_copies_named_candidate_and_never_scp_baseline(self) -> None:
        runner = _Runner([(0, "", ""), (0, "../models/yolov8n.pt\n", ""), (0, "", ""), (0, "/home/x/Huian_YOLO/rpi_app/deployment_backups/model_x.json\n", ""), (0, "", ""), (0, "", "")])
        service = ModelDeploymentService(command_runner=runner)
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "best.pt"; model.touch()
            result = service.deploy_model(model, "huian_person_v1.pt", restart_command="sudo systemctl restart huian")
        self.assertEqual(result.remote_model_path, "/home/x/Huian_YOLO/models/huian_person_v1.pt")
        scp = next(call for call in runner.calls if call[0] == "scp")
        self.assertTrue(scp[-1].endswith(":/home/x/Huian_YOLO/models/huian_person_v1.pt"))
        self.assertNotIn("yolov8n.pt", scp[-1])

    def test_switch_command_records_config_backup_and_previous_model(self) -> None:
        runner = _Runner([(0, "/home/x/Huian_YOLO/rpi_app/deployment_backups/model_x.json\n", "")])
        service = ModelDeploymentService(command_runner=runner)
        record = service._switch_config("huian_person_v1.pt", "../models/yolov8n.pt")
        self.assertIn("deployment_backups", record)
        self.assertEqual(runner.calls[0][:2], ["ssh", "huian-pi"])
        self.assertIn("base64", runner.calls[0][2])

    def test_failed_restart_requests_rollback_without_deleting_models(self) -> None:
        runner = _Runner([(0, "", ""), (0, "../models/yolov8n.pt\n", ""), (0, "", ""), (0, "/home/x/Huian_YOLO/rpi_app/deployment_backups/model_x.json\n", ""), (1, "", "restart failed"), (0, "", ""), (0, "", "")])
        service = ModelDeploymentService(command_runner=runner)
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "best.pt"; model.touch()
            with self.assertRaisesRegex(DeploymentError, "已自动回滚"):
                service.deploy_model(model, "huian_person_v1.pt", restart_command="restart-huian")
        ssh_commands = [call[2] for call in runner.calls if call[0] == "ssh"]
        self.assertFalse(any("rm " in command for command in ssh_commands))

    def test_rollback_restores_config_then_restarts(self) -> None:
        runner = _Runner()
        service = ModelDeploymentService(command_runner=runner)
        service.rollback("/home/x/Huian_YOLO/rpi_app/deployment_backups/model_x.json", restart_command="restart-huian")
        self.assertEqual(runner.calls[0][:2], ["ssh", "huian-pi"])
        self.assertEqual(runner.calls[1], ["ssh", "huian-pi", "restart-huian"])


if __name__ == "__main__":
    unittest.main()
