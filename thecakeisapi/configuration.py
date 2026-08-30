import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import Any

from .settings import Settings


EDITABLE_SETTING_KEYS = (
    "bose_speaker_ip",
    "aftertouch_base_url",
    "soundtouch_cli_command",
    "public_base_url",
    "bose_state_poll_interval_seconds",
)
MIN_BOSE_POLL_INTERVAL_SECONDS = 1.0
MAX_BOSE_POLL_INTERVAL_SECONDS = 300.0


class SettingsPersistenceError(ValueError):
    """Raised when editable settings cannot be validated or persisted."""


class SettingsConfigurationStore:
    def __init__(
        self,
        active_settings: Settings,
        config_path: Path | None = None,
    ) -> None:
        self.active_settings = active_settings
        self.config_path = (
            config_path
            or active_settings.config_path
            or Path(os.getenv("THECAKEISAPI_CONFIG", "config.json"))
        )
        self._lock = Lock()
        self._configured_values = editable_settings_from(active_settings)
        self._restart_required = False

    def read(self) -> dict[str, object]:
        with self._lock:
            return {
                "settings": dict(self._configured_values),
                "restart_required": self._restart_required,
            }

    def update(
        self,
        values: dict[str, str | float | None],
    ) -> dict[str, str | float | None]:
        normalized_values = _validated_editable_settings(
            self.active_settings,
            values,
        )

        with self._lock:
            config_values = _read_config_object(self.config_path)
            config_values.update(normalized_values)
            _write_json_atomically(self.config_path, config_values)
            self._configured_values = normalized_values
            self._restart_required = True
            return dict(self._configured_values)


def editable_settings_from(settings: Settings) -> dict[str, str | float | None]:
    return {
        "bose_speaker_ip": settings.bose_speaker_ip,
        "aftertouch_base_url": settings.aftertouch_base_url,
        "soundtouch_cli_command": settings.soundtouch_cli_command,
        "public_base_url": settings.public_base_url,
        "bose_state_poll_interval_seconds": settings.bose_state_poll_interval_seconds,
    }


def _validated_editable_settings(
    active_settings: Settings,
    values: dict[str, str | float | None],
) -> dict[str, str | float | None]:
    if set(values) != set(EDITABLE_SETTING_KEYS):
        raise SettingsPersistenceError("All supported settings must be provided")

    normalized_values: dict[str, str | float | None] = {
        "bose_speaker_ip": _optional_trimmed_string(values["bose_speaker_ip"]),
        "aftertouch_base_url": _optional_trimmed_string(values["aftertouch_base_url"]),
        "soundtouch_cli_command": _required_command(values["soundtouch_cli_command"]),
        "public_base_url": _optional_trimmed_string(values["public_base_url"]),
        "bose_state_poll_interval_seconds": _poll_interval(
            values["bose_state_poll_interval_seconds"],
        ),
    }

    try:
        replace(active_settings, **normalized_values).validate()
    except ValueError as error:
        raise SettingsPersistenceError(str(error)) from error

    return normalized_values


def _optional_trimmed_string(value: str | float | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SettingsPersistenceError("Configuration values must be strings")

    trimmed_value = value.strip()
    return trimmed_value or None


def _required_command(value: str | float | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SettingsPersistenceError("soundtouch_cli_command must not be empty")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise SettingsPersistenceError(
            "soundtouch_cli_command must be a command name or executable path",
        )
    return value.strip()


def _poll_interval(value: str | float | None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SettingsPersistenceError(
            "bose_state_poll_interval_seconds must be a number",
        )

    interval = float(value)
    if not MIN_BOSE_POLL_INTERVAL_SECONDS <= interval <= MAX_BOSE_POLL_INTERVAL_SECONDS:
        raise SettingsPersistenceError(
            "bose_state_poll_interval_seconds must be between 1 and 300 seconds",
        )
    return interval


def _read_config_object(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}

    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            config_values = json.load(config_file)
    except (OSError, json.JSONDecodeError) as error:
        raise SettingsPersistenceError(
            f"Could not read configuration file: {error}",
        ) from error

    if not isinstance(config_values, dict):
        raise SettingsPersistenceError("Configuration file must contain a JSON object")
    return config_values


def _write_json_atomically(config_path: Path, values: dict[str, Any]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(values, temporary_file, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, config_path)
    except OSError as error:
        raise SettingsPersistenceError(
            f"Could not save configuration file: {error}",
        ) from error
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass
