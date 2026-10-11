import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from thecakeisapi.bose import BosePlaybackState
from thecakeisapi.main import (
    LocalRadioPlayRequest,
    _play_track,
    _playback_status,
    _sync_local_playback,
    create_app,
)
from thecakeisapi.player import PlayerError
from thecakeisapi.playlist import QueueTrack
from thecakeisapi.settings import Settings


TEST_STREAM_URL = "https://radio.example/live?format=mp3&redirect=true"


def route_endpoint(app, path: str, method: str):
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == path and method in route.methods
    )


class FakeLocalPlayer:
    def __init__(self) -> None:
        self.state = "stopped"
        self.source: Path | str | None = None
        self.played_sources: list[Path | str] = []
        self.finished = False
        self.fail_on_play = False
        self.stop_count = 0
        self.pause_count = 0
        self.resume_count = 0
        self.seek_count = 0

    def play(self, source: Path | str) -> dict[str, object]:
        self.played_sources.append(source)
        if self.fail_on_play:
            self.state = "stopped"
            self.source = None
            raise PlayerError("mpv could not be started: simulated failure")
        self.state = "playing"
        self.source = source
        self.finished = False
        return self.status()

    def stop(self) -> dict[str, object]:
        self.stop_count += 1
        self.state = "stopped"
        self.source = None
        self.finished = False
        return self.status()

    def pause(self) -> dict[str, object]:
        self.pause_count += 1
        self.state = "paused"
        return self.status()

    def resume(self) -> dict[str, object]:
        self.resume_count += 1
        self.state = "playing"
        return self.status()

    def seek(self, _seconds: float) -> dict[str, object]:
        self.seek_count += 1
        return self.status()

    def consume_finished(self) -> bool:
        if not self.finished:
            return False
        self.finished = False
        self.state = "stopped"
        self.source = None
        return True

    def status(self) -> dict[str, object]:
        source = str(self.source) if self.source is not None else None
        return {
            "backend": "mpv",
            "state": self.state,
            "process_id": 123 if self.state != "stopped" else None,
            "path": source if isinstance(self.source, Path) else None,
            "source": source,
            "elapsed_seconds": 47.0 if self.state != "stopped" else None,
            "duration_seconds": 180.0 if self.state != "stopped" else None,
            "paused": self.state == "paused",
        }


class radio_test_app:
    def __enter__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        music_root = Path(self.temp_dir.name)
        for name in ("first.mp3", "second.mp3", "third.mp3"):
            (music_root / name).write_bytes(b"audio")
        self.app = create_app(Settings(music_root=music_root))
        self.app.state.playback_monitor_stop.set()
        self.app.state.local_player = FakeLocalPlayer()
        return self.app

    def __exit__(self, *args):
        self.app.state.playback_monitor_stop.set()
        self.app.state.playback_monitor.join(timeout=2)
        self.temp_dir.cleanup()


def queue_tracks() -> list[QueueTrack]:
    return [
        QueueTrack(path="first.mp3", name="first.mp3"),
        QueueTrack(path="second.mp3", name="second.mp3"),
        QueueTrack(path="third.mp3", name="third.mp3"),
    ]


def set_independent_queues(app) -> None:
    app.state.local_playback_queue.set_tracks(queue_tracks(), "first.mp3")
    app.state.bose_playback_queue.set_tracks(
        [QueueTrack(path="third.mp3", name="third.mp3")],
        "third.mp3",
    )


def start_radio(app, url: str = TEST_STREAM_URL, name: str = "Test Radio"):
    endpoint = route_endpoint(app, "/api/player/local/radio/play", "POST")
    return endpoint(LocalRadioPlayRequest(url=url, name=name))


class LocalRadioValidationTests(unittest.TestCase):
    def test_only_absolute_http_and_https_urls_are_accepted(self) -> None:
        for stream_url in (
            "http://radio.example/stream",
            "https://radio.example/stream?format=aac",
        ):
            request = LocalRadioPlayRequest(url=stream_url, name="Radio")
            self.assertEqual(request.url, stream_url)

        for stream_url in (
            "radio.example/stream",
            "ftp://radio.example/stream",
            "file:///tmp/stream",
            "https://user:secret@radio.example/stream",
        ):
            with self.subTest(stream_url=stream_url):
                with self.assertRaises(ValidationError):
                    LocalRadioPlayRequest(url=stream_url, name="Radio")

    def test_station_name_is_trimmed_and_extra_fields_are_rejected(self) -> None:
        request = LocalRadioPlayRequest(url=TEST_STREAM_URL, name="  Test Radio  ")
        self.assertEqual(request.name, "Test Radio")

        with self.assertRaises(ValidationError):
            LocalRadioPlayRequest(
                url=TEST_STREAM_URL,
                name="Test Radio",
                unexpected=True,
            )


class LocalRadioPlaybackTests(unittest.TestCase):
    def test_radio_start_bypasses_file_validation_and_preserves_queue_and_bose(self) -> None:
        with radio_test_app() as app:
            set_independent_queues(app)
            bose_state = BosePlaybackState(
                track_path="third.mp3",
                track_name="third.mp3",
                state="playing",
                ownership_stream_url="http://pi/audio?playback_id=owned",
                ownership_confirmed=True,
            )
            app.state.bose_playback_state = bose_state

            with patch("thecakeisapi.main.resolve_audio_file") as resolve_audio_file:
                status = start_radio(app)

            resolve_audio_file.assert_not_called()
            self.assertEqual(app.state.local_player.played_sources, [TEST_STREAM_URL])
            self.assertEqual(app.state.local_playback_queue.current().path, "first.mp3")
            self.assertEqual(app.state.bose_playback_queue.current().path, "third.mp3")
            self.assertIs(app.state.bose_playback_state, bose_state)
            self.assertTrue(app.state.bose_playback_state.ownership_confirmed)
            self.assertEqual(status["active_output"], "local")

    def test_active_radio_has_distinct_safe_local_projection(self) -> None:
        with radio_test_app() as app:
            set_independent_queues(app)

            status = start_radio(app, name="Example FM")
            local_status = status["outputs"]["local"]

            self.assertEqual(local_status["source_type"], "radio")
            self.assertEqual(local_status["source_name"], "Example FM")
            self.assertEqual(
                local_status["now_playing"],
                {"path": None, "name": "Example FM"},
            )
            self.assertIsNone(local_status["elapsed_seconds"])
            self.assertIsNone(local_status["duration_seconds"])
            self.assertFalse(local_status["paused"])
            self.assertNotIn(TEST_STREAM_URL, str(local_status["now_playing"]))
            self.assertEqual(status["now_playing"], local_status["now_playing"])
            self.assertNotEqual(status["now_playing"]["path"], "first.mp3")

    def test_stop_clears_radio_mode_then_resume_uses_preserved_file_cursor(self) -> None:
        with radio_test_app() as app:
            set_independent_queues(app)
            bose_state = BosePlaybackState(
                track_path="third.mp3",
                track_name="third.mp3",
                state="playing",
                ownership_stream_url="http://pi/audio?playback_id=owned",
                ownership_confirmed=True,
            )
            app.state.bose_playback_state = bose_state
            start_radio(app)

            stop_status = route_endpoint(app, "/api/player/local/stop", "POST")()

            self.assertIsNone(app.state.local_radio_state)
            self.assertEqual(stop_status["outputs"]["local"]["source_type"], "none")
            self.assertEqual(app.state.local_playback_queue.current().path, "first.mp3")
            self.assertEqual(app.state.bose_playback_queue.current().path, "third.mp3")
            self.assertIs(app.state.bose_playback_state, bose_state)
            self.assertTrue(app.state.bose_playback_state.ownership_confirmed)

            route_endpoint(app, "/api/player/local/resume", "POST")()

            resumed_source = app.state.local_player.played_sources[-1]
            self.assertIsInstance(resumed_source, Path)
            self.assertEqual(resumed_source.name, "first.mp3")
            self.assertNotEqual(resumed_source, TEST_STREAM_URL)

    def test_clear_queue_during_radio_leaves_radio_and_bose_queue_untouched(self) -> None:
        with radio_test_app() as app:
            set_independent_queues(app)
            start_radio(app)

            status = route_endpoint(app, "/api/player/local/queue/clear", "POST")()

            self.assertEqual(app.state.local_playback_queue.as_dict()["tracks"], [])
            self.assertEqual(app.state.bose_playback_queue.current().path, "third.mp3")
            self.assertIsNotNone(app.state.local_radio_state)
            self.assertEqual(app.state.local_player.state, "playing")
            self.assertEqual(app.state.local_player.source, TEST_STREAM_URL)
            self.assertEqual(app.state.local_player.stop_count, 0)
            self.assertEqual(status["outputs"]["local"]["source_type"], "radio")

    def test_radio_transport_guards_preserve_cursor_repeat_and_player(self) -> None:
        with radio_test_app() as app:
            set_independent_queues(app)
            app.state.repeat_track = True
            start_radio(app)
            local_cursor = app.state.local_playback_queue.current()

            route_endpoint(app, "/api/player/local/resume", "POST")()
            route_endpoint(app, "/api/player/local/pause", "POST")()
            route_endpoint(app, "/api/player/local/seek", "POST")(12.0)
            route_endpoint(app, "/api/player/local/next", "POST")()
            route_endpoint(app, "/api/player/local/previous", "POST")()
            route_endpoint(app, "/api/player/local/repeat", "POST")(False)

            self.assertEqual(app.state.local_playback_queue.current(), local_cursor)
            self.assertEqual(app.state.bose_playback_queue.current().path, "third.mp3")
            self.assertTrue(app.state.repeat_track)
            self.assertEqual(len(app.state.local_player.played_sources), 1)
            self.assertEqual(app.state.local_player.pause_count, 0)
            self.assertEqual(app.state.local_player.resume_count, 0)
            self.assertEqual(app.state.local_player.seek_count, 0)
            self.assertEqual(app.state.local_player.state, "playing")

    def test_radio_exit_records_failure_without_repeat_or_queue_advance(self) -> None:
        with radio_test_app() as app:
            set_independent_queues(app)
            bose_state = BosePlaybackState(
                track_path="third.mp3",
                track_name="third.mp3",
                state="playing",
                ownership_stream_url="http://pi/audio?playback_id=owned",
                ownership_confirmed=True,
            )
            app.state.bose_playback_state = bose_state
            app.state.repeat_track = True
            start_radio(app, name="Disconnecting Radio")
            app.state.local_player.finished = True

            _sync_local_playback(app)
            status = _playback_status(app)

            self.assertEqual(app.state.local_playback_queue.current().path, "first.mp3")
            self.assertEqual(app.state.bose_playback_queue.current().path, "third.mp3")
            self.assertIs(app.state.bose_playback_state, bose_state)
            self.assertTrue(app.state.bose_playback_state.ownership_confirmed)
            self.assertEqual(app.state.local_player.played_sources, [TEST_STREAM_URL])
            self.assertTrue(app.state.repeat_track)
            self.assertEqual(status["outputs"]["local"]["state"], "error")
            self.assertEqual(status["outputs"]["local"]["source_type"], "radio")
            self.assertIsNone(status["outputs"]["local"]["now_playing"])
            self.assertIsNone(status["now_playing"])
            self.assertIn("stopped unexpectedly", status["outputs"]["local"]["message"])

    def test_local_file_playback_clears_radio_error_metadata(self) -> None:
        with radio_test_app() as app:
            start_radio(app)
            app.state.local_player.finished = True
            _sync_local_playback(app)

            _play_track(app, QueueTrack(path="second.mp3", name="second.mp3"))
            status = _playback_status(app)

            self.assertIsNone(app.state.local_radio_state)
            self.assertEqual(status["outputs"]["local"]["source_type"], "library")
            self.assertEqual(status["outputs"]["local"]["now_playing"]["path"], "second.mp3")

    def test_mpv_launch_failure_uses_existing_service_unavailable_convention(self) -> None:
        with radio_test_app() as app:
            app.state.local_player.fail_on_play = True

            with self.assertRaises(HTTPException) as raised:
                start_radio(app)

            self.assertEqual(raised.exception.status_code, 503)
            self.assertIn("simulated failure", raised.exception.detail)
            self.assertIsNotNone(app.state.local_radio_state.error_message)

    def test_existing_local_file_route_does_not_accept_a_radio_url(self) -> None:
        with radio_test_app() as app:
            endpoint = route_endpoint(app, "/api/player/local/play", "POST")

            with self.assertRaises(HTTPException) as raised:
                endpoint(TEST_STREAM_URL, None)

            self.assertIn(raised.exception.status_code, {400, 404})
            self.assertEqual(app.state.local_player.played_sources, [])


if __name__ == "__main__":
    unittest.main()
