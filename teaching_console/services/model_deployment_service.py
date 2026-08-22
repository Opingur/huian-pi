"""SSH deployment helpers for accepted YOLO fine-tune candidate models.

This module deliberately never replaces ``yolov8n.pt``.  It only uploads a
candidate under its own name, records the previous JSON configuration remotely,
and switches the configured ``model_path`` atomically.  The caller must supply
the actual site restart command: this repository has no checked-in service name
and guessing one would be unsafe on a live Raspberry Pi.
"""
from __future__ import annotations

import base64
import json
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


class DeploymentError(RuntimeError):
    """A remote preflight, upload, switch, restart, or rollback failure."""


@dataclass(frozen=True)
class DeploymentSettings:
    ssh_alias: str = "huian-pi"
    remote_project_root: str = "/home/x/Huian_YOLO"
    config_relative_path: str = "rpi_app/config.json"
    models_relative_path: str = "models"

    @property
    def remote_config_path(self) -> str:
        return f"{self.remote_project_root}/{self.config_relative_path}"

    @property
    def remote_models_path(self) -> str:
        return f"{self.remote_project_root}/{self.models_relative_path}"


@dataclass(frozen=True)
class DeploymentResult:
    candidate_name: str
    remote_model_path: str
    previous_model_path: str
    rollback_record_path: str


def validate_candidate_name(candidate_name: str) -> str:
    """Allow only a simple candidate filename; the baseline is immutable."""
    name = Path(candidate_name).name
    if name != candidate_name or not name.endswith(".pt"):
        raise ValueError("候选模型名称必须是单个 .pt 文件名。")
    if name.lower() == "yolov8n.pt":
        raise ValueError("禁止覆盖基础模型 yolov8n.pt。")
    if not name or name in {".", ".."}:
        raise ValueError("候选模型名称不能为空。")
    return name


class ModelDeploymentService:
    """Run a narrow, rollback-capable deployment protocol over OpenSSH."""

    def __init__(
        self,
        settings: DeploymentSettings | None = None,
        *,
        command_runner: Callable[..., object] = subprocess.run,
    ) -> None:
        self.settings = settings or DeploymentSettings()
        self._run = command_runner

    def _command(self, args: list[str]) -> object:
        try:
            result = self._run(args, check=False, capture_output=True, text=True)
        except (FileNotFoundError, OSError) as error:
            raise DeploymentError(f"无法启动 SSH/SCP：{error}") from error
        if getattr(result, "returncode", 0) != 0:
            detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "命令返回非零状态").strip()
            raise DeploymentError(detail)
        return result

    def _ssh(self, remote_command: str) -> object:
        return self._command(["ssh", self.settings.ssh_alias, remote_command])

    @staticmethod
    def _remote_python(source: str, payload: dict[str, object]) -> str:
        """Pass fixed Python source plus JSON data without shell interpolation."""
        encoded_source = base64.b64encode(source.encode("utf-8")).decode("ascii")
        encoded_payload = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        return (
            "python3 -c "
            + shlex.quote(
                "import base64,json;scope={};exec(base64.b64decode(" + repr(encoded_source) + "),scope)"
                ";scope['main'](json.loads(base64.b64decode(" + repr(encoded_payload) + ")))"
            )
        )

    def check_ssh(self) -> None:
        """Verify alias, project, config, and model directory before any upload."""
        command = " && ".join((
            f"test -d {shlex.quote(self.settings.remote_project_root)}",
            f"test -f {shlex.quote(self.settings.remote_config_path)}",
            f"test -d {shlex.quote(self.settings.remote_models_path)}",
        ))
        self._ssh(command)

    def current_model_path(self) -> str:
        script = (
            "def main(data):\n"
            " import json\n"
            " with open(data['config_path'], encoding='utf-8') as handle: config=json.load(handle)\n"
            " print(config['model_path'])\n"
        )
        result = self._ssh(self._remote_python(script, {"config_path": self.settings.remote_config_path}))
        value = (getattr(result, "stdout", "") or "").strip()
        if not value:
            raise DeploymentError("远端 config.json 未返回当前 model_path。")
        return value

    def deploy_model(self, local_model: str | Path, candidate_name: str, *, restart_command: str) -> DeploymentResult:
        """Upload, switch config, restart the explicitly configured live program.

        If the requested restart fails, the just-written configuration is
        immediately restored from its saved rollback record.  Neither the
        candidate file nor the immutable baseline is deleted.
        """
        local_path = Path(local_model)
        if not local_path.is_file():
            raise FileNotFoundError(f"候选模型不存在：{local_path}")
        name = validate_candidate_name(candidate_name)
        if not restart_command.strip():
            raise ValueError("必须提供已核实的树莓派程序重启命令。")

        self.check_ssh()
        previous = self.current_model_path()
        remote_model_path = f"{self.settings.remote_models_path}/{name}"
        self._command(["scp", str(local_path), f"{self.settings.ssh_alias}:{remote_model_path}"])
        record_path = self._switch_config(name, previous)
        try:
            self._ssh(restart_command)
            self.run_self_check(name)
        except DeploymentError as error:
            try:
                self.rollback(record_path, restart_command=restart_command)
            except DeploymentError as rollback_error:
                raise DeploymentError(f"部署后的重启/自检失败：{error}；自动回滚也失败：{rollback_error}") from error
            raise DeploymentError(f"部署后的重启/自检失败，已自动回滚：{error}") from error
        return DeploymentResult(name, remote_model_path, previous, record_path)

    def _switch_config(self, candidate_name: str, previous_model_path: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        record_path = f"{self.settings.remote_project_root}/rpi_app/deployment_backups/model_{timestamp}.json"
        script = (
            "def main(data):\n"
            " import json,os,shutil\n"
            " config_path=data['config_path']; record_path=data['record_path']\n"
            " os.makedirs(os.path.dirname(record_path), exist_ok=True)\n"
            " backup_path=record_path.replace('.json', '.config.json')\n"
            " shutil.copy2(config_path, backup_path)\n"
            " with open(config_path, encoding='utf-8') as handle: config=json.load(handle)\n"
            " old=config.get('model_path')\n"
            " if old != data['previous_model_path']: raise RuntimeError('远端模型配置在部署期间发生变化')\n"
            " config['model_path']='../models/' + data['candidate_name']\n"
            " temp_path=config_path + '.huian-deploy.tmp'\n"
            " with open(temp_path, 'w', encoding='utf-8') as handle: json.dump(config, handle, ensure_ascii=False, indent=2)\n"
            " os.replace(temp_path, config_path)\n"
            " record={'config_path':config_path,'backup_path':backup_path,'previous_model_path':old,'deployed_model_path':config['model_path']}\n"
            " with open(record_path, 'w', encoding='utf-8') as handle: json.dump(record, handle, ensure_ascii=False, indent=2)\n"
            " print(record_path)\n"
        )
        result = self._ssh(self._remote_python(script, {
            "config_path": self.settings.remote_config_path,
            "record_path": record_path,
            "candidate_name": candidate_name,
            "previous_model_path": previous_model_path,
        }))
        returned_path = (getattr(result, "stdout", "") or "").strip()
        return returned_path or record_path

    def run_self_check(self, candidate_name: str) -> None:
        """Check config/model consistency without loading weights or changing state."""
        name = validate_candidate_name(candidate_name)
        script = (
            "def main(data):\n"
            " import json,os\n"
            " with open(data['config_path'], encoding='utf-8') as handle: config=json.load(handle)\n"
            " expected='../models/' + data['candidate_name']\n"
            " if config.get('model_path') != expected: raise RuntimeError('model_path 未指向候选模型')\n"
            " if not os.path.isfile(data['model_path']): raise RuntimeError('候选模型文件不存在')\n"
        )
        self._ssh(self._remote_python(script, {
            "config_path": self.settings.remote_config_path,
            "candidate_name": name,
            "model_path": f"{self.settings.remote_models_path}/{name}",
        }))

    def rollback(self, rollback_record_path: str, *, restart_command: str) -> None:
        """Restore the exact backed-up config, keep every model file intact."""
        if not rollback_record_path.startswith(self.settings.remote_project_root + "/"):
            raise ValueError("回滚记录必须位于当前树莓派项目目录。")
        if not restart_command.strip():
            raise ValueError("必须提供已核实的树莓派程序重启命令。")
        script = (
            "def main(data):\n"
            " import json,os,shutil\n"
            " with open(data['record_path'], encoding='utf-8') as handle: record=json.load(handle)\n"
            " if not os.path.isfile(record['backup_path']): raise RuntimeError('找不到 config 备份')\n"
            " shutil.copy2(record['backup_path'], record['config_path'])\n"
        )
        self._ssh(self._remote_python(script, {"record_path": rollback_record_path}))
        self._ssh(restart_command)
