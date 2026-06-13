import json
import os
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    music_root: Path = Path("/mnt/music")
    bose_speaker_ip: str | None = None
    bose_api_port: int = 8090
    aftertouch_base_url: str | None = None
    public_base_url: str | None = None
    soundtouch_cli_command: str = "soundtouch-cli"
    mpv_command: str = "mpv"
    mpv_ipc_path: Path = Path("/tmp/thecakeisapi-mpv.sock")
    config_path: Path | None = field(default=None, repr=False)

    @classmethod
    def load(cls, config_path: Path | str | None = None) -> "Settings":
        resolved_config_path = cls._resolve_config_path(config_path)
        config_values = cls._read_config_file(resolved_config_path)

        music_root = os.getenv(
            "THECAKEISAPI_MUSIC_ROOT",
            cls._read_string(config_values, "music_root", str(cls.music_root)),
        )
        bose_speaker_ip = os.getenv(
            "THECAKEISAPI_BOSE_SPEAKER_IP",
            cls._read_optional_string(config_values, "bose_speaker_ip"),
        )
        bose_api_port = os.getenv(
            "THECAKEISAPI_BOSE_API_PORT",
            str(cls._read_int(config_values, "bose_api_port", cls.bose_api_port)),
        )
        aftertouch_base_url = os.getenv(
            "THECAKEISAPI_AFTERTOUCH_BASE_URL",
            cls._read_optional_string(config_values, "aftertouch_base_url"),
        )
        public_base_url = os.getenv(
            "THECAKEISAPI_PUBLIC_BASE_URL",
            cls._read_optional_string(config_values, "public_base_url"),
        )
        soundtouch_cli_command = os.getenv(
            "THECAKEISAPI_SOUNDTOUCH_CLI_COMMAND",
            cls._read_string(
                config_values,
                "soundtouch_cli_command",
                cls.soundtouch_cli_command,
            ),
        )
        mpv_command = os.getenv(
            "THECAKEISAPI_MPV_COMMAND",
            cls._read_string(config_values, "mpv_command", cls.mpv_command),
        )
        mpv_ipc_path = os.getenv(
            "THECAKEISAPI_MPV_IPC_PATH",
            cls._read_string(config_values, "mpv_ipc_path", str(cls.mpv_ipc_path)),
        )

        settings = cls(
            music_root=Path(music_root),
            bose_speaker_ip=bose_speaker_ip,
            bose_api_port=cls._parse_int("bose_api_port", bose_api_port),
            aftertouch_base_url=aftertouch_base_url,
            public_base_url=public_base_url,
            soundtouch_cli_command=soundtouch_cli_command,
            mpv_command=mpv_command,
            mpv_ipc_path=Path(mpv_ipc_path),
            config_path=resolved_config_path if resolved_config_path.exists() else None,
        )
        settings.validate()
        return settings

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls.load()

    def validate(self) -> None:
        if not str(self.music_root).strip():
            raise ValueError("music_root must not be empty")

        if not self.mpv_command.strip():
            raise ValueError("mpv_command must not be empty")

        if not str(self.mpv_ipc_path).strip():
            raise ValueError("mpv_ipc_path must not be empty")

        if not self.soundtouch_cli_command.strip():
            raise ValueError("soundtouch_cli_command must not be empty")

        if self.bose_speaker_ip not in ("", None):
            try:
                ip_address(self.bose_speaker_ip)
            except ValueError as error:
                raise ValueError("bose_speaker_ip must be a valid IP address") from error

        if self.bose_api_port < 1 or self.bose_api_port > 65535:
            raise ValueError("bose_api_port must be between 1 and 65535")

        self._validate_optional_url("aftertouch_base_url", self.aftertouch_base_url)
        self._validate_optional_url("public_base_url", self.public_base_url)

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "music_root": str(self.music_root),
            "bose_speaker_ip": self.bose_speaker_ip,
            "bose_api_port": self.bose_api_port,
            "aftertouch_base_url": self.aftertouch_base_url,
            "public_base_url": self.public_base_url,
            "soundtouch_cli_command": self.soundtouch_cli_command,
            "mpv_command": self.mpv_command,
            "mpv_ipc_path": str(self.mpv_ipc_path),
            "config_path": str(self.config_path) if self.config_path else None,
        }

    @staticmethod
    def _resolve_config_path(config_path: Path | str | None) -> Path:
        configured_path = config_path or os.getenv("THECAKEISAPI_CONFIG", "config.json")
        return Path(configured_path)

    @staticmethod
    def _read_config_file(config_path: Path) -> dict[str, Any]:
        if not config_path.exists():
            return {}

        try:
            with config_path.open("r", encoding="utf-8") as config_file:
                config_values = json.load(config_file)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON in settings file: {config_path}") from error

        if not isinstance(config_values, dict):
            raise ValueError("Settings file must contain a JSON object")

        allowed_keys = {
            "music_root",
            "bose_speaker_ip",
            "bose_api_port",
            "aftertouch_base_url",
            "public_base_url",
            "soundtouch_cli_command",
            "mpv_command",
            "mpv_ipc_path",
        }
        unknown_keys = sorted(set(config_values) - allowed_keys)
        if unknown_keys:
            joined_keys = ", ".join(unknown_keys)
            raise ValueError(f"Unknown settings: {joined_keys}")

        return config_values

    @staticmethod
    def _read_string(
        config_values: dict[str, Any],
        key: str,
        default: str,
    ) -> str:
        value = config_values.get(key, default)
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        return value

    @staticmethod
    def _read_optional_string(
        config_values: dict[str, Any],
        key: str,
    ) -> str | None:
        value = config_values.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string or null")
        return value

    @staticmethod
    def _read_int(config_values: dict[str, Any], key: str, default: int) -> int:
        value = config_values.get(key, default)
        if not isinstance(value, int):
            raise ValueError(f"{key} must be an integer")
        return value

    @staticmethod
    def _parse_int(key: str, value: str) -> int:
        try:
            return int(value)
        except ValueError as error:
            raise ValueError(f"{key} must be an integer") from error

    @staticmethod
    def _validate_optional_url(key: str, value: str | None) -> None:
        if value in ("", None):
            return

        parsed_url = urlparse(value)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError(f"{key} must be an HTTP or HTTPS URL")
