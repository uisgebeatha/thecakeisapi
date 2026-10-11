import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from thecakeisapi.bose import (
    BoseNowPlayingStatus,
    BosePlaybackRequest,
    BosePlaybackState,
    SoundTouchCliClient,
    parse_now_playing,
)
from thecakeisapi.main import (
    _observe_external_bose_playback,
    _pause_bose_playback,
    _play_bose_track,
    _playback_status,
    _poll_bose_playback_state,
    _resume_bose_playback,
    _stop_bose_playback,
    _sync_bose_playback,
    create_app,
)
from thecakeisapi.minidlna import MiniDlnaPathError
from thecakeisapi.playlist import QueueTrack
from thecakeisapi.settings import (
    BOSE_PLAYBACK_METHOD_AFTERTOUCH,
    BOSE_PLAYBACK_METHOD_STORED_MUSIC,
    Settings,
)


SOURCE_ACCOUNT = "4d696e69-444c-164e-9d41-e45f01636b02/0"


def stored_music_status(
    source_account: str,
    content_location: str,
    track_name: str = "first.mp3",
    play_status: str = "PLAY_STATE",
    source: str = "STORED_MUSIC",
) -> BoseNowPlayingStatus:
    return parse_now_playing(
        f'<nowPlaying source="{source}">'
        f'<ContentItem source="{source}" sourceAccount="{source_account}" '
        f'location="{content_location}" type="track">'
        f"<itemName>{track_name}</itemName>"
        "</ContentItem>"
        f"<track>{track_name}</track>"
        f"<playStatus>{play_status}</playStatus>"
        "</nowPlaying>",
    )


def native_owned_state(**overrides) -> BosePlaybackState:
    values = {
        "track_path": "first.mp3",
        "track_name": "first.mp3",
        "state": "playing",
        "confirmed_start_timestamp": time.time() - 4,
        "duration_seconds": 30.0,
        "playback_method": BOSE_PLAYBACK_METHOD_STORED_MUSIC,
        "ownership_source_account": SOURCE_ACCOUNT,
        "ownership_content_location": "64$0$0 TRACK",
        "ownership_confirmed": True,
    }
    values.update(overrides)
    return BosePlaybackState(**values)


class StoredMusicCommandTests(unittest.TestCase):
    def test_native_command_uses_raw_object_id_plus_track_suffix(self) -> None:
        command = SoundTouchCliClient(
            "soundtouch-cli",
            "192.168.42.101",
            "http://aftertouch.local:8001",
        ).build_stored_music_track_command(
            "Air - Moon Safari.flac",
            SOURCE_ACCOUNT,
            "64$0$0",
        )

        self.assertEqual(
            command,
            [
                "soundtouch-cli",
                "--host",
                "192.168.42.101",
                "library",
                "play",
                "--source-account",
                SOURCE_ACCOUNT,
                "--location",
                "64$0$0 TRACK",
                "--type",
                "track",
                "--name",
                "Air - Moon Safari.flac",
            ],
        )

    @patch("thecakeisapi.bose.subprocess.run")
    def test_native_play_runs_soundtouch_cli_command(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )
        client = SoundTouchCliClient(
            "soundtouch-cli",
            "192.168.42.101",
            "http://aftertouch.local:8001",
        )

        request = client.play_stored_music_track(
            "Air - Moon Safari.flac",
            SOURCE_ACCOUNT,
            "64$0$0",
        )

        self.assertEqual(request.content_location, "64$0$0 TRACK")
        run_mock.assert_called_once_with(
            client.build_stored_music_track_command(
                "Air - Moon Safari.flac",
                SOURCE_ACCOUNT,
                "64$0$0",
            ),
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )


class StoredMusicPlaybackTests(unittest.TestCase):
    def test_default_method_keeps_custom_radio_path_unchanged(self) -> None:
        with native_music_app(
            playback_method=BOSE_PLAYBACK_METHOD_AFTERTOUCH,
        ) as app:
            app.state.active_output = "bose"
            _play_bose_track(app, QueueTrack(path="first.mp3", name="first.mp3"))

            self.assertEqual(len(app.state.bose_client.custom_calls), 1)
            self.assertEqual(app.state.bose_client.native_calls, [])
            self.assertEqual(
                app.state.bose_playback_state.playback_method,
                BOSE_PLAYBACK_METHOD_AFTERTOUCH,
            )
            self.assertTrue(app.state.bose_playback_state.ownership_confirmed)
            status = _playback_status(app)
            self.assertEqual(status["backend"], "bose_aftertouch")
            self.assertEqual(
                status["outputs"]["bose"]["backend"],
                "bose_aftertouch",
            )
            self.assertEqual(
                status["outputs"]["bose"]["app_playback_method"],
                BOSE_PLAYBACK_METHOD_AFTERTOUCH,
            )
            self.assertEqual(
                status["bose"]["app_playback_method"],
                BOSE_PLAYBACK_METHOD_AFTERTOUCH,
            )

    def test_native_track_resolves_absolute_path_and_confirms_ownership(self) -> None:
        with native_music_app() as app:
            app.state.active_output = "bose"
            _play_bose_track(app, QueueTrack(path="first.mp3", name="first.mp3"))

            expected_path = app.state.settings.music_root.resolve() / "first.mp3"
            self.assertEqual(app.state.minidlna_resolver.paths, [expected_path])
            self.assertEqual(
                app.state.bose_client.native_calls,
                [("first.mp3", SOURCE_ACCOUNT, "64$0$0")],
            )
            self.assertEqual(
                app.state.bose_now_playing_client.native_confirmations,
                [(SOURCE_ACCOUNT, "64$0$0 TRACK")],
            )
            self.assertTrue(app.state.bose_playback_state.ownership_confirmed)
            self.assertEqual(app.state.bose_playback_state.state, "playing")
            status = _playback_status(app)
            self.assertEqual(status["backend"], "bose_aftertouch")
            self.assertEqual(
                status["outputs"]["bose"]["backend"],
                "bose_aftertouch",
            )
            self.assertEqual(
                status["outputs"]["bose"]["app_playback_method"],
                BOSE_PLAYBACK_METHOD_STORED_MUSIC,
            )
            self.assertEqual(
                status["bose"]["app_playback_method"],
                BOSE_PLAYBACK_METHOD_STORED_MUSIC,
            )

    def test_resolver_failure_falls_back_before_native_command(self) -> None:
        with native_music_app() as app:
            app.state.minidlna_resolver.error = MiniDlnaPathError("not indexed")

            _play_bose_track(app, QueueTrack(path="first.mp3", name="first.mp3"))

            self.assertEqual(app.state.bose_client.native_calls, [])
            self.assertEqual(len(app.state.bose_client.custom_calls), 1)
            self.assertIn("using AfterTouch", app.state.bose_playback_state.warning)
            self.assertTrue(app.state.bose_playback_state.ownership_confirmed)

    def test_missing_source_account_falls_back_before_resolver_or_command(self) -> None:
        with native_music_app(source_account=None) as app:
            _play_bose_track(app, QueueTrack(path="first.mp3", name="first.mp3"))

            self.assertEqual(app.state.minidlna_resolver.paths, [])
            self.assertEqual(app.state.bose_client.native_calls, [])
            self.assertEqual(len(app.state.bose_client.custom_calls), 1)

    def test_failed_native_confirmation_does_not_start_custom_radio(self) -> None:
        with native_music_app() as app:
            app.state.bose_now_playing_client.confirm_native = False

            _play_bose_track(app, QueueTrack(path="first.mp3", name="first.mp3"))

            self.assertEqual(len(app.state.bose_client.native_calls), 1)
            self.assertEqual(app.state.bose_client.custom_calls, [])
            self.assertEqual(app.state.bose_playback_state.state, "starting")
            self.assertFalse(app.state.bose_playback_state.ownership_confirmed)
            self.assertIn("confirmation timed out", app.state.bose_playback_state.warning)

    def test_passive_stored_music_observation_remains_external(self) -> None:
        with native_music_app() as app:
            app.state.bose_playback_state = BosePlaybackState()
            app.state.bose_now_playing_client.statuses = [
                stored_music_status(SOURCE_ACCOUNT, "64$0$0 TRACK"),
            ]

            _observe_external_bose_playback(app, now_monotonic=10.0)

            self.assertTrue(app.state.bose_playback_state.external_playback_active)
            self.assertFalse(app.state.bose_playback_state.ownership_confirmed)
            self.assertFalse(app.state.bose_playback_state.has_app_ownership_context)

    def test_native_identity_mismatch_clears_ownership_and_preserves_queue(self) -> None:
        mismatched_statuses = {
            "source": stored_music_status(
                SOURCE_ACCOUNT,
                "64$0$0 TRACK",
                source="AUX",
            ),
            "source account": stored_music_status(
                "different-account/0",
                "64$0$0 TRACK",
            ),
            "location": stored_music_status(
                SOURCE_ACCOUNT,
                "64$9$9 TRACK",
                "other.mp3",
            ),
        }

        for mismatch, status in mismatched_statuses.items():
            with self.subTest(mismatch=mismatch), native_music_app() as app:
                app.state.bose_playback_queue.set_tracks(
                    [
                        QueueTrack(path="first.mp3", name="first.mp3"),
                        QueueTrack(path="second.mp3", name="second.mp3"),
                    ],
                    "first.mp3",
                )
                app.state.bose_playback_state = native_owned_state()
                app.state.bose_now_playing_client.statuses = [status]

                _poll_bose_playback_state(app, now_monotonic=10.0)

                self.assertTrue(app.state.bose_playback_state.external_playback_active)
                self.assertFalse(app.state.bose_playback_state.has_app_ownership_context)
                self.assertEqual(
                    [
                        track["path"]
                        for track in app.state.bose_playback_queue.as_dict()["tracks"]
                    ],
                    ["first.mp3", "second.mp3"],
                )
                self.assertEqual(
                    app.state.bose_playback_queue.current().path,
                    "first.mp3",
                )
                app.state.active_output = "bose"
                projected_status = _playback_status(app)
                self.assertEqual(
                    projected_status["backend"],
                    "bose_aftertouch",
                )
                self.assertEqual(
                    projected_status["outputs"]["bose"]["backend"],
                    "bose_aftertouch",
                )
                self.assertIsNone(
                    projected_status["outputs"]["bose"]["app_playback_method"],
                )
                self.assertIsNone(
                    projected_status["bose"]["app_playback_method"],
                )

    def test_native_pause_and_resume_preserve_elapsed_position(self) -> None:
        with native_music_app() as app:
            app.state.bose_playback_state = native_owned_state()

            _pause_bose_playback(app)
            paused_elapsed = app.state.bose_playback_state.paused_elapsed_seconds
            _resume_bose_playback(app)

            self.assertTrue(app.state.bose_client.paused)
            self.assertTrue(app.state.bose_client.resumed)
            self.assertGreater(paused_elapsed, 3.0)
            self.assertGreater(app.state.bose_playback_state.elapsed_seconds(), 3.0)
            self.assertEqual(app.state.bose_playback_state.state, "playing")

    def test_native_stop_projects_paused_state_and_preserves_queue(self) -> None:
        with native_music_app() as app:
            app.state.bose_playback_queue.set_tracks(
                [QueueTrack(path="first.mp3", name="first.mp3")],
                "first.mp3",
            )
            app.state.bose_playback_state = native_owned_state()
            app.state.bose_now_playing_client.statuses = [
                stored_music_status(SOURCE_ACCOUNT, "64$0$0 TRACK"),
            ]

            self.assertTrue(_stop_bose_playback(app))

            status = _playback_status(app)
            self.assertTrue(app.state.bose_client.stopped)
            self.assertEqual(app.state.bose_playback_state.state, "paused")
            self.assertTrue(status["outputs"]["bose"]["paused"])
            self.assertEqual(app.state.bose_playback_queue.current().path, "first.mp3")

    def test_matching_stop_state_keeps_clock_running_until_auto_advance(self) -> None:
        with native_music_app() as app:
            app.state.bose_playback_queue.set_tracks(
                [
                    QueueTrack(path="first.mp3", name="first.mp3"),
                    QueueTrack(path="second.mp3", name="second.mp3"),
                ],
                "first.mp3",
            )
            app.state.bose_playback_state = native_owned_state(
                confirmed_start_timestamp=100.0,
                duration_seconds=5.0,
            )
            app.state.bose_now_playing_client.statuses = [
                stored_music_status(
                    SOURCE_ACCOUNT,
                    "64$0$0 TRACK",
                    play_status="STOP_STATE",
                ),
            ]

            with patch("thecakeisapi.bose.time.time", return_value=104.0):
                _sync_bose_playback(app)

            self.assertEqual(app.state.bose_playback_state.state, "playing")
            self.assertIsNone(
                app.state.bose_playback_state.paused_elapsed_seconds,
            )
            self.assertTrue(app.state.bose_playback_state.ownership_confirmed)
            self.assertEqual(
                app.state.bose_playback_queue.current().path,
                "first.mp3",
            )
            self.assertEqual(app.state.bose_client.native_calls, [])

            with patch("thecakeisapi.bose.time.time", return_value=106.0):
                _sync_bose_playback(app)

            self.assertEqual(
                app.state.bose_playback_queue.current().path,
                "second.mp3",
            )
            self.assertEqual(
                app.state.bose_client.native_calls,
                [("second.mp3", SOURCE_ACCOUNT, "64$0$1")],
            )

    def test_matching_pause_state_freezes_elapsed_time(self) -> None:
        with native_music_app() as app:
            app.state.bose_playback_state = native_owned_state(
                confirmed_start_timestamp=100.0,
                duration_seconds=30.0,
            )
            app.state.bose_now_playing_client.statuses = [
                stored_music_status(
                    SOURCE_ACCOUNT,
                    "64$0$0 TRACK",
                    play_status="PAUSE_STATE",
                ),
            ]

            with patch("thecakeisapi.bose.time.time", return_value=104.0):
                _sync_bose_playback(app)

            self.assertEqual(app.state.bose_playback_state.state, "paused")
            self.assertEqual(
                app.state.bose_playback_state.paused_elapsed_seconds,
                4.0,
            )
            self.assertTrue(app.state.bose_playback_state.ownership_confirmed)

    def test_existing_auto_advance_starts_next_native_track(self) -> None:
        with native_music_app() as app:
            app.state.bose_playback_queue.set_tracks(
                [
                    QueueTrack(path="first.mp3", name="first.mp3"),
                    QueueTrack(path="second.mp3", name="second.mp3"),
                ],
                "first.mp3",
            )
            app.state.bose_playback_state = native_owned_state(
                confirmed_start_timestamp=time.time() - 3,
                duration_seconds=1.0,
            )
            app.state.bose_now_playing_client.statuses = [
                stored_music_status(SOURCE_ACCOUNT, "64$0$0 TRACK"),
            ]

            _sync_bose_playback(app)

            self.assertEqual(app.state.bose_playback_queue.current().path, "second.mp3")
            self.assertEqual(
                app.state.bose_client.native_calls,
                [("second.mp3", SOURCE_ACCOUNT, "64$0$1")],
            )
            self.assertEqual(app.state.bose_client.custom_calls, [])
            self.assertTrue(app.state.bose_playback_state.ownership_confirmed)


class FakeMiniDlnaResolver:
    def __init__(self) -> None:
        self.paths: list[Path] = []
        self.error: Exception | None = None

    def resolve_audio_file(self, path: Path) -> str:
        self.paths.append(path)
        if self.error:
            raise self.error
        return {
            "first.mp3": "64$0$0",
            "second.mp3": "64$0$1",
            "third.mp3": "64$0$2",
        }[path.name]


class FakeBoseClient:
    def __init__(self) -> None:
        self.custom_calls: list[tuple[str, str]] = []
        self.native_calls: list[tuple[str, str, str]] = []
        self.stopped = False
        self.paused = False
        self.resumed = False

    def play_stream(self, name: str, stream_url: str) -> BosePlaybackRequest:
        self.custom_calls.append((name, stream_url))
        return BosePlaybackRequest(stream_url=stream_url, command=["custom-radio"])

    def play_stored_music_track(
        self,
        name: str,
        source_account: str,
        object_id: str,
    ) -> BosePlaybackRequest:
        self.native_calls.append((name, source_account, object_id))
        return BosePlaybackRequest(
            command=["stored-music"],
            content_location=f"{object_id} TRACK",
        )

    def stop(self) -> None:
        self.stopped = True

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.resumed = True


class FakeNowPlayingClient:
    def __init__(self) -> None:
        self.statuses: list[BoseNowPlayingStatus] = []
        self.confirm_native = True
        self.native_confirmations: list[tuple[str, str]] = []
        self.custom_confirmations: list[str] = []

    def fetch_status(self) -> BoseNowPlayingStatus:
        if self.statuses:
            return self.statuses.pop(0)
        return parse_now_playing('<nowPlaying source="STANDBY" />')

    def wait_for_custom_radio(
        self,
        _timeout_seconds: float,
        _poll_interval_seconds: float,
        _previous_status: BoseNowPlayingStatus | None,
        expected_stream_url: str,
    ) -> BoseNowPlayingStatus:
        self.custom_confirmations.append(expected_stream_url)
        return parse_now_playing(
            '<nowPlaying source="LOCAL_INTERNET_RADIO">'
            f'<ContentItem source="LOCAL_INTERNET_RADIO" location="{expected_stream_url}" />'
            "<playStatus>PLAY_STATE</playStatus>"
            "</nowPlaying>",
        )

    def wait_for_stored_music_track(
        self,
        _timeout_seconds: float,
        _poll_interval_seconds: float,
        expected_source_account: str,
        expected_content_location: str,
    ) -> BoseNowPlayingStatus | None:
        self.native_confirmations.append(
            (expected_source_account, expected_content_location),
        )
        if not self.confirm_native:
            return None
        return stored_music_status(
            expected_source_account,
            expected_content_location,
        )


class native_music_app:
    def __init__(
        self,
        playback_method: str = BOSE_PLAYBACK_METHOD_STORED_MUSIC,
        source_account: str | None = SOURCE_ACCOUNT,
    ) -> None:
        self.playback_method = playback_method
        self.source_account = source_account

    def __enter__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        music_root = Path(self.temp_dir.name)
        for name in ("first.mp3", "second.mp3", "third.mp3"):
            (music_root / name).write_bytes(b"\xff\xfb\x90d" + (b"\0" * 1000))

        self.app = create_app(
            Settings(
                music_root=music_root,
                bose_speaker_ip="192.168.42.101",
                aftertouch_base_url="http://aftertouch.local:8001",
                public_base_url="http://pi.local:8000",
                bose_playback_method=self.playback_method,
                bose_stored_music_source_account=self.source_account,
                bose_start_confirm_timeout_seconds=0.01,
                bose_start_poll_interval_seconds=0.001,
                bose_auto_advance_buffer_seconds=0.5,
            ),
        )
        self.app.state.playback_monitor_stop.set()
        self.app.state.bose_client = FakeBoseClient()
        self.app.state.bose_now_playing_client = FakeNowPlayingClient()
        self.app.state.minidlna_resolver = FakeMiniDlnaResolver()
        return self.app

    def __exit__(self, *args):
        self.app.state.playback_monitor_stop.set()
        self.temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
