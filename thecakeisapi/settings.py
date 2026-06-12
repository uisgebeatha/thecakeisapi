import json
import os
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    music_root: Path = Path("/mnt/music")
    bose_speaker_ip: str | None = None
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

        settings = cls(
            music_root=Path(music_root),
            bose_speaker_ip=bose_speaker_ip,
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

        if self.bose_speaker_ip in ("", None):
            return

        try:
            ip_address(self.bose_speaker_ip)
        except ValueError as error:
            raise ValueError("bose_speaker_ip must be a valid IP address") from error

    def as_dict(self) -> dict[str, str | None]:
        return {
            "music_root": str(self.music_root),
            "bose_speaker_ip": self.bose_speaker_ip,
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

        allowed_keys = {"music_root", "bose_speaker_ip"}
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
