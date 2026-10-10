import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
from uuid import UUID, uuid4


LOGGER = logging.getLogger(__name__)
MAX_RADIO_NAME_LENGTH = 200
MAX_RADIO_URL_LENGTH = 2048


class RadioPresetError(ValueError):
    """Base error for local radio preset operations."""


class RadioPresetStorageError(RadioPresetError):
    """Raised when local radio presets cannot be loaded or saved."""


class RadioPresetNotFoundError(RadioPresetError):
    """Raised when a local radio preset does not exist."""


class RadioPresetOrderConflictError(RadioPresetError):
    """Raised when a reorder request does not match the stored presets."""


@dataclass(frozen=True)
class RadioPreset:
    id: str
    name: str
    url: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
        }


def normalize_radio_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Radio name must be a string")

    display_name = value.strip()
    if not display_name:
        raise ValueError("Radio name must not be blank")
    if len(display_name) > MAX_RADIO_NAME_LENGTH:
        raise ValueError(
            f"Radio name must not exceed {MAX_RADIO_NAME_LENGTH} characters",
        )
    return display_name


def normalize_radio_url(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Radio URL must be a string")

    stream_url = value.strip()
    if not stream_url:
        raise ValueError("Radio URL must not be blank")
    if len(stream_url) > MAX_RADIO_URL_LENGTH:
        raise ValueError(
            f"Radio URL must not exceed {MAX_RADIO_URL_LENGTH} characters",
        )
    if any(character.isspace() for character in stream_url):
        raise ValueError("Radio URL must not contain whitespace")

    try:
        parsed_url = urlsplit(stream_url)
        hostname = parsed_url.hostname
        parsed_url.port
    except ValueError as error:
        raise ValueError("Radio URL is invalid") from error

    if parsed_url.scheme.lower() not in {"http", "https"} or not hostname:
        raise ValueError("Radio URL must be an absolute HTTP or HTTPS URL")
    if parsed_url.username is not None or parsed_url.password is not None:
        raise ValueError("Radio URL must not contain credentials")
    return stream_url


class RadioPresetStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self._presets: list[RadioPreset] = []
        self._load_error: RadioPresetStorageError | None = None

        try:
            self._presets = self._load()
        except RadioPresetStorageError as error:
            self._load_error = error
            LOGGER.error("Local radio presets are unavailable: %s", error)

    def list_presets(self) -> list[RadioPreset]:
        with self._lock:
            self._require_available()
            return list(self._presets)

    def get(self, preset_id: UUID | str) -> RadioPreset:
        normalized_id = str(preset_id)
        with self._lock:
            self._require_available()
            return self._find(normalized_id)

    def create(self, name: object, url: object) -> RadioPreset:
        normalized_name = normalize_radio_name(name)
        normalized_url = normalize_radio_url(url)

        with self._lock:
            self._require_available()
            preset = RadioPreset(
                id=str(uuid4()),
                name=normalized_name,
                url=normalized_url,
            )
            updated_presets = [*self._presets, preset]
            self._write(updated_presets)
            self._presets = updated_presets
        return preset

    def update(self, preset_id: UUID | str, name: object, url: object) -> RadioPreset:
        normalized_id = str(preset_id)
        normalized_name = normalize_radio_name(name)
        normalized_url = normalize_radio_url(url)

        with self._lock:
            self._require_available()
            current = self._find(normalized_id)
            updated = RadioPreset(
                id=current.id,
                name=normalized_name,
                url=normalized_url,
            )
            updated_presets = [
                updated if preset.id == normalized_id else preset
                for preset in self._presets
            ]
            self._write(updated_presets)
            self._presets = updated_presets
            return updated

    def delete(self, preset_id: UUID | str) -> None:
        normalized_id = str(preset_id)
        with self._lock:
            self._require_available()
            self._find(normalized_id)
            updated_presets = [
                preset for preset in self._presets if preset.id != normalized_id
            ]
            self._write(updated_presets)
            self._presets = updated_presets

    def reorder(self, preset_ids: list[UUID | str]) -> list[RadioPreset]:
        normalized_ids = [str(preset_id) for preset_id in preset_ids]
        with self._lock:
            self._require_available()
            current_ids = [preset.id for preset in self._presets]
            if (
                len(normalized_ids) != len(current_ids)
                or len(set(normalized_ids)) != len(normalized_ids)
                or set(normalized_ids) != set(current_ids)
            ):
                raise RadioPresetOrderConflictError(
                    "Preset order must contain every current preset id exactly once",
                )

            presets_by_id = {preset.id: preset for preset in self._presets}
            updated_presets = [presets_by_id[preset_id] for preset_id in normalized_ids]
            self._write(updated_presets)
            self._presets = updated_presets
            return list(self._presets)

    def _require_available(self) -> None:
        if self._load_error is not None:
            raise RadioPresetStorageError(
                "Local radio presets are unavailable because the preset file is invalid",
            ) from self._load_error

    def _find(self, preset_id: str) -> RadioPreset:
        for preset in self._presets:
            if preset.id == preset_id:
                return preset
        raise RadioPresetNotFoundError("Local radio preset was not found")

    def _load(self) -> list[RadioPreset]:
        if not self.path.exists():
            return []

        try:
            with self.path.open("r", encoding="utf-8") as preset_file:
                payload = json.load(preset_file)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RadioPresetStorageError(
                f"Could not read radio preset file {self.path}: {error}",
            ) from error

        if not isinstance(payload, dict) or set(payload) != {"presets"}:
            raise RadioPresetStorageError(
                "Radio preset file must contain an object with only a presets array",
            )
        raw_presets = payload["presets"]
        if not isinstance(raw_presets, list):
            raise RadioPresetStorageError(
                "Radio preset file's presets field must be an array",
            )

        presets: list[RadioPreset] = []
        seen_ids: set[str] = set()
        for raw_preset in raw_presets:
            preset = self._parse_preset(raw_preset)
            if preset.id in seen_ids:
                raise RadioPresetStorageError(
                    f"Radio preset file contains duplicate id {preset.id}",
                )
            seen_ids.add(preset.id)
            presets.append(preset)
        return presets

    @staticmethod
    def _parse_preset(raw_preset: object) -> RadioPreset:
        if (
            not isinstance(raw_preset, dict)
            or set(raw_preset) != {"id", "name", "url"}
        ):
            raise RadioPresetStorageError(
                "Each radio preset must contain only id, name, and url",
            )

        raw_id = raw_preset["id"]
        if not isinstance(raw_id, str):
            raise RadioPresetStorageError("Radio preset id must be a UUID string")
        try:
            parsed_id = UUID(raw_id)
        except ValueError as error:
            raise RadioPresetStorageError("Radio preset id must be a valid UUID") from error
        if parsed_id.version != 4 or str(parsed_id) != raw_id:
            raise RadioPresetStorageError(
                "Radio preset id must be a canonical UUIDv4 string",
            )

        try:
            name = normalize_radio_name(raw_preset["name"])
            url = normalize_radio_url(raw_preset["url"])
        except ValueError as error:
            raise RadioPresetStorageError(str(error)) from error

        return RadioPreset(id=raw_id, name=name, url=url)

    def _write(self, presets: list[RadioPreset]) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(
                    {"presets": [preset.as_dict() for preset in presets]},
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, self.path)
        except OSError as error:
            LOGGER.error("Could not save local radio presets: %s", error)
            raise RadioPresetStorageError(
                "Could not save local radio presets",
            ) from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
