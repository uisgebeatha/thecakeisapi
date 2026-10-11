import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from thecakeisapi import main as main_module
from thecakeisapi.bose import BosePlaybackState
from thecakeisapi.main import (
    LocalRadioPlayRequest,
    RadioPresetOrderRequest,
    create_app,
)
from thecakeisapi.player import PlayerError
from thecakeisapi.playlist import QueueTrack
from thecakeisapi.radio_presets import RadioPresetStorageError, RadioPresetStore
from thecakeisapi.settings import Settings


FIRST_URL = "https://radio.example/first"
SECOND_URL = "https://radio.example/second"
TEST_TEMP_ROOT = Path(__file__).resolve().parents[1]


def temporary_directory():
    return tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)


def route(app, path: str, method: str):
    return next(
        candidate
        for candidate in app.routes
        if getattr(candidate, "path", None) == path
        and method in getattr(candidate, "methods", set())
    )


def endpoint(app, path: str, method: str):
    return route(app, path, method).endpoint


class FakeLocalPlayer:
    def __init__(self) -> None:
        self.state = "stopped"
        self.source: Path | str | None = None
        self.played_sources: list[Path | str] = []
        self.fail_on_play = False

    def play(self, source: Path | str) -> dict[str, object]:
        self.played_sources.append(source)
        if self.fail_on_play:
            self.state = "stopped"
            self.source = None
            raise PlayerError("simulated radio failure")
        self.state = "playing"
        self.source = source
        return self.status()

    def stop(self) -> dict[str, object]:
        self.state = "stopped"
        self.source = None
        return self.status()

    def consume_finished(self) -> bool:
        return False

    def status(self) -> dict[str, object]:
        source = str(self.source) if self.source is not None else None
        return {
            "backend": "mpv",
            "state": self.state,
            "process_id": 123 if self.state == "playing" else None,
            "path": source if isinstance(self.source, Path) else None,
            "source": source,
            "elapsed_seconds": None,
            "duration_seconds": None,
            "paused": False,
        }


class preset_test_app:
    def __enter__(self):
        self.temp_dir = temporary_directory()
        root = Path(self.temp_dir.name)
        for name in ("first.mp3", "second.mp3"):
            (root / name).write_bytes(b"audio")
        self.app = create_app(
            Settings(
                music_root=root,
                config_path=root / "config.json",
            ),
        )
        self.app.state.playback_monitor_stop.set()
        self.app.state.local_player = FakeLocalPlayer()
        return self.app

    def __exit__(self, *args):
        self.app.state.playback_monitor_stop.set()
        self.app.state.playback_monitor.join(timeout=2)
        self.temp_dir.cleanup()


class RadioPresetStoreTests(unittest.TestCase):
    def test_missing_file_is_empty_without_creating_a_file(self) -> None:
        with temporary_directory() as temp_dir:
            path = Path(temp_dir) / "radio_presets.json"
            store = RadioPresetStore(path)

            self.assertEqual(store.list_presets(), [])
            self.assertFalse(path.exists())

    def test_unicode_round_trip_order_and_stable_ids(self) -> None:
        with temporary_directory() as temp_dir:
            path = Path(temp_dir) / "radio_presets.json"
            store = RadioPresetStore(path)
            first = store.create("  日本語ラジオ 🎵  ", FIRST_URL)
            second = store.create("Second", SECOND_URL)

            updated = store.update(first.id, "日本語ラジオ 改", FIRST_URL)
            reordered = store.reorder([second.id, first.id])
            reloaded = RadioPresetStore(path).list_presets()

            self.assertEqual(updated.id, first.id)
            self.assertEqual([preset.id for preset in reordered], [second.id, first.id])
            self.assertEqual([preset.id for preset in reloaded], [second.id, first.id])
            self.assertEqual(reloaded[1].name, "日本語ラジオ 改")
            self.assertIn("日本語ラジオ 改", path.read_text(encoding="utf-8"))
            self.assertNotIn("\\u65e5", path.read_text(encoding="utf-8"))

    def test_deleting_last_preset_writes_explicit_empty_structure(self) -> None:
        with temporary_directory() as temp_dir:
            path = Path(temp_dir) / "radio_presets.json"
            store = RadioPresetStore(path)
            preset = store.create("Only", FIRST_URL)

            store.delete(preset.id)

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"presets": []})
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))

    def test_corrupt_files_disable_store_without_overwrite(self) -> None:
        duplicate_id = "0e7ebde0-0d38-49ff-8fef-d68369b9b828"
        corrupt_contents = (
            "{not json",
            json.dumps({"presets": "not-an-array"}),
            json.dumps({"presets": [{"id": "bad", "name": "Radio", "url": FIRST_URL}]}),
            json.dumps(
                {
                    "presets": [
                        {"id": duplicate_id, "name": "One", "url": FIRST_URL},
                        {"id": duplicate_id, "name": "Two", "url": SECOND_URL},
                    ],
                },
            ),
            json.dumps(
                {
                    "presets": [
                        {"id": duplicate_id, "name": "   ", "url": FIRST_URL},
                    ],
                },
            ),
            json.dumps(
                {
                    "presets": [
                        {"id": duplicate_id, "name": "Radio", "url": "ftp://bad"},
                    ],
                },
            ),
        )

        for original in corrupt_contents:
            with self.subTest(original=original):
                with temporary_directory() as temp_dir:
                    path = Path(temp_dir) / "radio_presets.json"
                    path.write_text(original, encoding="utf-8")
                    store = RadioPresetStore(path)

                    with self.assertRaises(RadioPresetStorageError):
                        store.list_presets()
                    with self.assertRaises(RadioPresetStorageError):
                        store.create("New", FIRST_URL)
                    self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_atomic_replace_uses_same_directory(self) -> None:
        with temporary_directory() as temp_dir:
            path = Path(temp_dir) / "radio_presets.json"
            store = RadioPresetStore(path)

            with patch("thecakeisapi.radio_presets.os.replace", wraps=os.replace) as replace:
                store.create("Radio", FIRST_URL)

            temporary_path, replaced_path = replace.call_args.args
            self.assertEqual(Path(temporary_path).parent, path.parent)
            self.assertEqual(Path(replaced_path), path)
            self.assertFalse(Path(temporary_path).exists())

    def test_failed_replace_preserves_disk_and_memory(self) -> None:
        with temporary_directory() as temp_dir:
            path = Path(temp_dir) / "radio_presets.json"
            store = RadioPresetStore(path)
            first = store.create("First", FIRST_URL)
            original = path.read_text(encoding="utf-8")

            with patch(
                "thecakeisapi.radio_presets.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaises(RadioPresetStorageError):
                    store.create("Second", SECOND_URL)

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual([preset.id for preset in store.list_presets()], [first.id])
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_failed_write_preserves_disk_and_memory(self) -> None:
        with temporary_directory() as temp_dir:
            path = Path(temp_dir) / "radio_presets.json"
            store = RadioPresetStore(path)
            first = store.create("First", FIRST_URL)
            original = path.read_text(encoding="utf-8")

            with patch(
                "thecakeisapi.radio_presets.json.dump",
                side_effect=OSError("write failed"),
            ):
                with self.assertRaises(RadioPresetStorageError):
                    store.update(first.id, "Changed", SECOND_URL)

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(store.get(first.id).name, "First")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])


class RadioPresetApiTests(unittest.TestCase):
    def test_crud_reorder_duplicates_and_response_codes(self) -> None:
        with preset_test_app() as app:
            list_endpoint = endpoint(app, "/api/player/local/radio/presets", "GET")
            create_route = route(app, "/api/player/local/radio/presets", "POST")
            update_endpoint = endpoint(
                app,
                "/api/player/local/radio/presets/{preset_id}",
                "PUT",
            )
            reorder_endpoint = endpoint(
                app,
                "/api/player/local/radio/presets/order",
                "PUT",
            )
            delete_route = route(
                app,
                "/api/player/local/radio/presets/{preset_id}",
                "DELETE",
            )

            self.assertEqual(list_endpoint(), {"presets": []})
            first = create_route.endpoint(
                LocalRadioPlayRequest(name="Duplicate", url=FIRST_URL),
            )
            second = create_route.endpoint(
                LocalRadioPlayRequest(name="Duplicate", url=FIRST_URL),
            )
            updated = update_endpoint(
                UUID(first["id"]),
                LocalRadioPlayRequest(name="Updated", url=SECOND_URL),
            )
            ordered = reorder_endpoint(
                RadioPresetOrderRequest(
                    preset_ids=[UUID(second["id"]), UUID(first["id"])],
                ),
            )
            deleted = delete_route.endpoint(UUID(second["id"]))

            self.assertEqual(create_route.status_code, 201)
            self.assertEqual(delete_route.status_code, 204)
            self.assertEqual(updated["id"], first["id"])
            self.assertEqual(updated["name"], "Updated")
            self.assertEqual(
                [preset["id"] for preset in ordered["presets"]],
                [second["id"], first["id"]],
            )
            self.assertEqual(deleted.status_code, 204)
            self.assertEqual(
                [preset["id"] for preset in list_endpoint()["presets"]],
                [first["id"]],
            )

    def test_invalid_unknown_and_conflicting_ids_use_expected_status(self) -> None:
        with preset_test_app() as app:
            put_paths = [
                candidate.path
                for candidate in app.routes
                if "PUT" in getattr(candidate, "methods", set())
            ]
            self.assertLess(
                put_paths.index("/api/player/local/radio/presets/order"),
                put_paths.index("/api/player/local/radio/presets/{preset_id}"),
            )
            create = endpoint(app, "/api/player/local/radio/presets", "POST")
            update = endpoint(
                app,
                "/api/player/local/radio/presets/{preset_id}",
                "PUT",
            )
            delete = endpoint(
                app,
                "/api/player/local/radio/presets/{preset_id}",
                "DELETE",
            )
            play = endpoint(
                app,
                "/api/player/local/radio/presets/{preset_id}/play",
                "POST",
            )
            reorder = endpoint(
                app,
                "/api/player/local/radio/presets/order",
                "PUT",
            )
            preset = create(LocalRadioPlayRequest(name="One", url=FIRST_URL))
            unknown = UUID("fd21228b-1327-4e73-bd29-b8860b07c4a9")

            with self.assertRaises(ValidationError):
                TypeAdapter(UUID).validate_python("not-a-uuid")
            self.assertIs(
                inspect.signature(update).parameters["preset_id"].annotation,
                UUID,
            )
            for call in (
                lambda: update(unknown, LocalRadioPlayRequest(name="X", url=FIRST_URL)),
                lambda: delete(unknown),
                lambda: play(unknown),
            ):
                with self.subTest(call=call):
                    with self.assertRaises(HTTPException) as raised:
                        call()
                    self.assertEqual(raised.exception.status_code, 404)

            invalid_orders = (
                [],
                [UUID(preset["id"]), UUID(preset["id"])],
                [unknown],
                [UUID(preset["id"]), unknown],
            )
            for preset_ids in invalid_orders:
                with self.subTest(preset_ids=preset_ids):
                    with self.assertRaises(HTTPException) as raised:
                        reorder(RadioPresetOrderRequest(preset_ids=preset_ids))
                    self.assertEqual(raised.exception.status_code, 409)

    def test_preset_and_transient_routes_share_validation_without_network_checks(self) -> None:
        with preset_test_app() as app:
            create = endpoint(app, "/api/player/local/radio/presets", "POST")

            preset_request = LocalRadioPlayRequest(
                name="  Unicode 日本 🎵  ",
                url="  https://radio.example/live  ",
            )
            created = create(preset_request)

            self.assertEqual(preset_request.name, "Unicode 日本 🎵")
            self.assertEqual(preset_request.url, "https://radio.example/live")
            self.assertEqual(created["name"], preset_request.name)
            self.assertEqual(app.state.local_player.played_sources, [])
            for values in (
                {"name": "   ", "url": FIRST_URL},
                {"name": "Radio", "url": "ftp://radio.example/live"},
                {"name": "Radio", "url": "https://user:secret@radio.example/live"},
            ):
                with self.subTest(values=values):
                    with self.assertRaises(ValidationError):
                        LocalRadioPlayRequest(**values)

    def test_play_uses_latest_server_value_and_preserves_queue_bose_and_repeat(self) -> None:
        with preset_test_app() as app:
            tracks = [
                QueueTrack(path="first.mp3", name="first.mp3"),
                QueueTrack(path="second.mp3", name="second.mp3"),
            ]
            app.state.local_playback_queue.set_tracks(tracks, "first.mp3")
            app.state.bose_playback_queue.set_tracks(
                [QueueTrack(path="second.mp3", name="second.mp3")],
                "second.mp3",
            )
            app.state.repeat_track = True
            bose_state = BosePlaybackState(
                track_path="second.mp3",
                track_name="second.mp3",
                state="playing",
                ownership_stream_url="http://pi/audio?playback_id=owned",
                ownership_confirmed=True,
            )
            app.state.bose_playback_state = bose_state

            create = endpoint(app, "/api/player/local/radio/presets", "POST")
            update = endpoint(
                app,
                "/api/player/local/radio/presets/{preset_id}",
                "PUT",
            )
            play = endpoint(
                app,
                "/api/player/local/radio/presets/{preset_id}/play",
                "POST",
            )
            preset = create(LocalRadioPlayRequest(name="Old", url=FIRST_URL))
            preset_id = UUID(preset["id"])
            update(
                preset_id,
                LocalRadioPlayRequest(name="Current", url=SECOND_URL),
            )

            with patch(
                "thecakeisapi.main._play_local_radio",
                wraps=main_module._play_local_radio,
            ) as play_helper:
                status = play(preset_id)

            play_helper.assert_called_once_with(app, SECOND_URL, "Current")
            self.assertEqual(app.state.local_player.played_sources, [SECOND_URL])
            self.assertEqual(app.state.local_playback_queue.current().path, "first.mp3")
            self.assertEqual(app.state.bose_playback_queue.current().path, "second.mp3")
            self.assertTrue(app.state.repeat_track)
            self.assertIs(app.state.bose_playback_state, bose_state)
            self.assertEqual(status["active_output"], "local")
            self.assertEqual(status["outputs"]["local"]["source_name"], "Current")

    def test_crud_and_active_edit_delete_do_not_change_playback_state(self) -> None:
        with preset_test_app() as app:
            tracks = [QueueTrack(path="first.mp3", name="first.mp3")]
            app.state.local_playback_queue.set_tracks(tracks, "first.mp3")
            app.state.bose_playback_queue.set_tracks(tracks, "first.mp3")
            app.state.repeat_track = True
            bose_state = BosePlaybackState(state="stopped")
            app.state.bose_playback_state = bose_state

            create = endpoint(app, "/api/player/local/radio/presets", "POST")
            update = endpoint(
                app,
                "/api/player/local/radio/presets/{preset_id}",
                "PUT",
            )
            delete = endpoint(
                app,
                "/api/player/local/radio/presets/{preset_id}",
                "DELETE",
            )
            reorder = endpoint(
                app,
                "/api/player/local/radio/presets/order",
                "PUT",
            )
            play = endpoint(
                app,
                "/api/player/local/radio/presets/{preset_id}/play",
                "POST",
            )
            preset = create(LocalRadioPlayRequest(name="Playing", url=FIRST_URL))
            preset_id = UUID(preset["id"])
            other = create(LocalRadioPlayRequest(name="Other", url=SECOND_URL))
            reorder(
                RadioPresetOrderRequest(
                    preset_ids=[UUID(other["id"]), preset_id],
                ),
            )
            delete(UUID(other["id"]))

            self.assertEqual(app.state.local_player.played_sources, [])
            self.assertIsNone(app.state.local_radio_state)
            play(preset_id)
            active_state = app.state.local_radio_state
            update(
                preset_id,
                LocalRadioPlayRequest(name="Changed", url=SECOND_URL),
            )
            delete(preset_id)

            self.assertIs(app.state.local_radio_state, active_state)
            self.assertEqual(active_state.display_name, "Playing")
            self.assertEqual(active_state.stream_url, FIRST_URL)
            self.assertEqual(app.state.local_player.source, FIRST_URL)
            self.assertEqual(app.state.local_playback_queue.current().path, "first.mp3")
            self.assertEqual(app.state.bose_playback_queue.current().path, "first.mp3")
            self.assertTrue(app.state.repeat_track)
            self.assertIs(app.state.bose_playback_state, bose_state)

    def test_failed_playback_leaves_preset_stored(self) -> None:
        with preset_test_app() as app:
            create = endpoint(app, "/api/player/local/radio/presets", "POST")
            read = endpoint(app, "/api/player/local/radio/presets", "GET")
            play = endpoint(
                app,
                "/api/player/local/radio/presets/{preset_id}/play",
                "POST",
            )
            preset = create(LocalRadioPlayRequest(name="Broken", url=FIRST_URL))
            app.state.local_player.fail_on_play = True

            with self.assertRaises(HTTPException) as raised:
                play(UUID(preset["id"]))

            self.assertEqual(raised.exception.status_code, 503)
            self.assertEqual(read()["presets"], [preset])

    def test_corrupt_storage_returns_service_unavailable_without_affecting_app(self) -> None:
        with preset_test_app() as app:
            path = app.state.radio_preset_store.path
            path.write_text("{bad", encoding="utf-8")
            app.state.radio_preset_store = RadioPresetStore(path)
            read = endpoint(app, "/api/player/local/radio/presets", "GET")

            with self.assertRaises(HTTPException) as raised:
                read()

            self.assertEqual(raised.exception.status_code, 503)
            self.assertEqual(path.read_text(encoding="utf-8"), "{bad")
            self.assertEqual(endpoint(app, "/api/health", "GET")()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
