import json
import re
import subprocess
import time
from threading import Lock
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


VERSION_PATTERN = re.compile(
    r"\bv?\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?\b",
)


class ComponentStatusProvider:
    def __init__(
        self,
        app_version: str,
        aftertouch_base_url: str | None,
        soundtouch_cli_command: str,
        cache_seconds: float = 300.0,
    ) -> None:
        self.app_version = app_version
        self.aftertouch_base_url = aftertouch_base_url
        self.soundtouch_cli_command = soundtouch_cli_command
        self.cache_seconds = cache_seconds
        self._cached_status: dict[str, dict[str, str]] | None = None
        self._cache_expires_monotonic = 0.0
        self._lock = Lock()

    def get_status(self) -> dict[str, dict[str, str]]:
        with self._lock:
            if (
                self._cached_status is not None
                and time.monotonic() < self._cache_expires_monotonic
            ):
                return _copy_status(self._cached_status)

            status = {
                "thecakeisapi": _component("TheCakeIsAPI", self.app_version),
                "aftertouch": _aftertouch_status(self.aftertouch_base_url),
                "soundtouch_cli": _soundtouch_cli_status(
                    self.soundtouch_cli_command,
                ),
            }
            self._cached_status = status
            self._cache_expires_monotonic = time.monotonic() + self.cache_seconds
            return _copy_status(status)


def _aftertouch_status(base_url: str | None) -> dict[str, str]:
    if not base_url:
        return _component("AfterTouch", "Unavailable", "unavailable")

    health_url = urljoin(base_url.rstrip("/") + "/", "health")
    request = Request(health_url, method="GET")
    try:
        with urlopen(request, timeout=3) as response:
            health = json.loads(response.read().decode("utf-8"))
    except (URLError, OSError, TimeoutError, json.JSONDecodeError):
        return _component("AfterTouch", "Unavailable", "unavailable")

    version = health.get("version") if isinstance(health, dict) else None
    if not isinstance(version, str) or not version.strip():
        return _component("AfterTouch", "Unknown", "unknown")
    return _component("AfterTouch", version.strip())


def _soundtouch_cli_status(command: str) -> dict[str, str]:
    try:
        completed_process = subprocess.run(
            [command, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return _component("soundtouch-cli", "Unavailable", "unavailable")

    if completed_process.returncode != 0:
        return _component("soundtouch-cli", "Unavailable", "unavailable")

    output = completed_process.stdout.strip() or completed_process.stderr.strip()
    version_match = VERSION_PATTERN.search(output)
    if version_match is None:
        return _component("soundtouch-cli", "Unknown", "unknown")
    return _component("soundtouch-cli", version_match.group(0))


def _component(
    name: str,
    version: str,
    status: str = "available",
) -> dict[str, str]:
    return {
        "name": name,
        "version": version,
        "status": status,
    }


def _copy_status(
    status: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    return {component_id: dict(values) for component_id, values in status.items()}
