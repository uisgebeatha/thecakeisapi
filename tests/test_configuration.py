import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from thecakeisapi.configuration import (
    EDITABLE_SETTING_KEYS,
    SettingsConfigurationStore,
    SettingsPersistenceError,
)
from thecakeisapi.main import SettingsUpdateRequest, create_app
from thecakeisapi.settings import Settings


class SettingsApiTests(unittest.TestCase):
    def test_get_only_exposes_supported_editable_fields(self) -> None:
        with temporary_settings_app() as (app, _config_path):
            response = route_endpoint(app, "/api/settings", "GET")()

            self.assertEqual(set(response["settings"]), set(EDITABLE_SETTING_KEYS))
            self.assertFalse(response["restart_required"])
            self.assertNotIn("music_root", response["settings"])
            self.assertNotIn("config_path", response["settings"])
            self.assertNotIn("private_token", response["settings"])

    def test_update_persists_allowed_fields_and_requires_restart(self) -> None:
        with temporary_settings_app() as (app, config_path):
            request = valid_update_request(
                bose_speaker_ip="bose-speaker.local",
                bose_state_poll_interval_seconds=12.5,
            )

            response = route_endpoint(app, "/api/settings", "PUT")(request)
            saved_config = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertTrue(response["restart_required"])
            self.assertIn("Restart", response["message"])
            self.assertEqual(response["settings"]["bose_speaker_ip"], "bose-speaker.local")
            self.assertEqual(saved_config["bose_speaker_ip"], "bose-speaker.local")
            self.assertEqual(saved_config["bose_state_poll_interval_seconds"], 12.5)
            self.assertTrue(
                route_endpoint(app, "/api/settings", "GET")()["restart_required"],
            )

    def test_update_preserves_unrelated_config_values(self) -> None:
        with temporary_settings_app() as (app, config_path):
            route_endpoint(app, "/api/settings", "PUT")(valid_update_request())
            saved_config = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(saved_config["music_root"], "/media/music")
            self.assertEqual(saved_config["private_token"], "do-not-expose")
            self.assertEqual(saved_config["bose_api_port"], 8090)

    def test_invalid_address_and_urls_return_useful_errors(self) -> None:
        invalid_values = (
            ("bose_speaker_ip", "http://speaker", "IP address or hostname"),
            ("aftertouch_base_url", "ftp://aftertouch.local", "HTTP or HTTPS URL"),
            ("public_base_url", "not-a-url", "HTTP or HTTPS URL"),
            ("public_base_url", "http://bad host:8000", "HTTP or HTTPS URL"),
            ("soundtouch_cli_command", "bad\ncommand", "command name or executable path"),
        )

        with temporary_settings_app() as (app, _config_path):
            update_endpoint = route_endpoint(app, "/api/settings", "PUT")
            for field_name, value, expected_message in invalid_values:
                with self.subTest(field_name=field_name):
                    request = valid_update_request(**{field_name: value})
                    with self.assertRaises(HTTPException) as raised:
                        update_endpoint(request)
                    self.assertEqual(raised.exception.status_code, 422)
                    self.assertIn(expected_message, raised.exception.detail)

    def test_invalid_poll_interval_is_rejected_by_request_model(self) -> None:
        for interval in (0, 301):
            with self.subTest(interval=interval):
                with self.assertRaises(ValidationError):
                    valid_update_request(
                        bose_state_poll_interval_seconds=interval,
                    )

    def test_health_endpoint_keeps_central_version(self) -> None:
        with temporary_settings_app() as (app, _config_path):
            response = route_endpoint(app, "/api/health", "GET")()

            self.assertEqual(response, {"status": "ok", "version": "0.4.3"})


class SettingsPersistenceTests(unittest.TestCase):
    def test_atomic_write_replaces_same_directory_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = SettingsConfigurationStore(
                Settings(config_path=config_path),
                config_path,
            )

            with patch(
                "thecakeisapi.configuration.os.replace",
                wraps=os.replace,
            ) as replace_mock:
                store.update(valid_update_request().model_dump())

            temporary_path, replaced_path = replace_mock.call_args.args
            self.assertEqual(Path(temporary_path).parent, config_path.parent)
            self.assertNotEqual(Path(temporary_path), config_path)
            self.assertEqual(Path(replaced_path), config_path)
            self.assertFalse(Path(temporary_path).exists())

    def test_failed_atomic_replace_leaves_original_file_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            original_contents = '{"music_root": "/media/music"}\n'
            config_path.write_text(original_contents, encoding="utf-8")
            store = SettingsConfigurationStore(
                Settings(config_path=config_path),
                config_path,
            )

            with patch(
                "thecakeisapi.configuration.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaises(SettingsPersistenceError):
                    store.update(valid_update_request().model_dump())

            self.assertEqual(
                config_path.read_text(encoding="utf-8"),
                original_contents,
            )
            self.assertEqual(list(config_path.parent.glob("*.tmp")), [])


def valid_update_request(**overrides) -> SettingsUpdateRequest:
    values = {
        "bose_speaker_ip": "192.168.42.101",
        "aftertouch_base_url": "http://aftertouch.local:8001",
        "soundtouch_cli_command": "/usr/local/bin/soundtouch-cli",
        "public_base_url": "http://pi.local:8000",
        "bose_state_poll_interval_seconds": 5.0,
    }
    values.update(overrides)
    return SettingsUpdateRequest(**values)


def route_endpoint(app, path: str, method: str):
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == path
        and method in getattr(route, "methods", set())
    )


class temporary_settings_app:
    def __enter__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "music_root": "/media/music",
                    "bose_api_port": 8090,
                    "private_token": "do-not-expose",
                },
            ),
            encoding="utf-8",
        )
        self.app = create_app(
            Settings(
                music_root=Path(self.temp_dir.name),
                bose_speaker_ip="192.168.42.101",
                aftertouch_base_url="http://aftertouch.local:8001",
                public_base_url="http://pi.local:8000",
                config_path=self.config_path,
            ),
        )
        self.app.state.playback_monitor_stop.set()
        return self.app, self.config_path

    def __exit__(self, *args):
        self.app.state.playback_monitor_stop.set()
        self.temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
