import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from thecakeisapi.component_status import (
    ComponentStatusProvider,
    _aftertouch_status,
    _soundtouch_cli_status,
)
from thecakeisapi.main import create_app
from thecakeisapi.settings import Settings

from tests.test_configuration import route_endpoint


class ComponentDetectionTests(unittest.TestCase):
    @patch("thecakeisapi.component_status.urlopen")
    def test_aftertouch_version_comes_from_health_endpoint(self, urlopen_mock) -> None:
        urlopen_mock.return_value = FakeResponse(b'{"version":"v0.120.0"}')

        status = _aftertouch_status("http://aftertouch.local:8001")

        self.assertEqual(status["version"], "v0.120.0")
        self.assertEqual(status["status"], "available")
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "http://aftertouch.local:8001/health")

    @patch(
        "thecakeisapi.component_status.urlopen",
        side_effect=URLError("offline"),
    )
    def test_unavailable_aftertouch_fails_gracefully(self, _urlopen_mock) -> None:
        status = _aftertouch_status("http://aftertouch.local:8001")

        self.assertEqual(status["version"], "Unavailable")
        self.assertEqual(status["status"], "unavailable")

    @patch("thecakeisapi.component_status.subprocess.run")
    def test_soundtouch_cli_version_uses_version_flag(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="soundtouch-cli v0.120.0\n",
            stderr="",
        )

        status = _soundtouch_cli_status("/usr/local/bin/soundtouch-cli")

        self.assertEqual(status["version"], "v0.120.0")
        run_mock.assert_called_once_with(
            ["/usr/local/bin/soundtouch-cli", "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )

    @patch(
        "thecakeisapi.component_status.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_unavailable_soundtouch_cli_fails_gracefully(self, _run_mock) -> None:
        status = _soundtouch_cli_status("missing-soundtouch-cli")

        self.assertEqual(status["version"], "Unavailable")
        self.assertEqual(status["status"], "unavailable")

    @patch("thecakeisapi.component_status._soundtouch_cli_status")
    @patch("thecakeisapi.component_status._aftertouch_status")
    def test_component_probe_results_are_cached(
        self,
        aftertouch_status_mock,
        cli_status_mock,
    ) -> None:
        aftertouch_status_mock.return_value = {
            "name": "AfterTouch",
            "version": "v0.120.0",
            "status": "available",
        }
        cli_status_mock.return_value = {
            "name": "soundtouch-cli",
            "version": "v0.120.0",
            "status": "available",
        }
        provider = ComponentStatusProvider(
            "0.4.3",
            "http://aftertouch.local:8001",
            "soundtouch-cli",
        )

        first_status = provider.get_status()
        second_status = provider.get_status()

        self.assertEqual(first_status, second_status)
        aftertouch_status_mock.assert_called_once()
        cli_status_mock.assert_called_once()


class ComponentStatusApiTests(unittest.TestCase):
    def test_component_status_endpoint_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Settings(music_root=Path(temp_dir)))
            app.state.playback_monitor_stop.set()
            app.state.component_status_provider = FakeComponentStatusProvider()

            response = route_endpoint(app, "/api/components/status", "GET")()
            component_route = next(
                route
                for route in app.routes
                if getattr(route, "path", None) == "/api/components/status"
            )

            self.assertEqual(
                response["components"]["thecakeisapi"]["version"],
                "0.4.3",
            )
            self.assertEqual(component_route.methods, {"GET"})


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self.body


class FakeComponentStatusProvider:
    def get_status(self):
        return {
            "thecakeisapi": {
                "name": "TheCakeIsAPI",
                "version": "0.4.3",
                "status": "available",
            },
            "aftertouch": {
                "name": "AfterTouch",
                "version": "Unavailable",
                "status": "unavailable",
            },
            "soundtouch_cli": {
                "name": "soundtouch-cli",
                "version": "Unavailable",
                "status": "unavailable",
            },
        }


if __name__ == "__main__":
    unittest.main()
