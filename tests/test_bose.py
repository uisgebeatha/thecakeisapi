import base64
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from thecakeisapi.bose import (
    AfterTouchClient,
    BoseNowPlayingClient,
    BoseNowPlayingStatus,
    BosePlaybackRequest,
    BosePlaybackState,
    BosePlaybackError,
    SoundTouchCliClient,
    build_library_stream_url,
    parse_now_playing,
)
from thecakeisapi.main import (
    _stop_bose_playback,
    _sync_bose_playback,
    create_app,
)
from thecakeisapi.playlist import QueueTrack
from thecakeisapi.settings import Settings


class AfterTouchClientTests(unittest.TestCase):
    def test_custom_playback_url_uses_base64_encoded_stream_url(self) -> None:
        stream_url = "http://192.168.42.190:8000/api/library/file?path=Album+One%2Fsong.mp3"

        playback_url = AfterTouchClient(
            "http://bose-controller.local",
        ).build_custom_playback_url(stream_url)

        playback_prefix = "http://bose-controller.local/custom/v1/playback/"
        self.assertTrue(playback_url.startswith(playback_prefix))
        encoded_stream_url = playback_url.removeprefix(playback_prefix)
        self.assertEqual(
            encoded_stream_url,
            base64.b64encode(stream_url.encode("utf-8")).decode("ascii"),
        )
        self.assertNotIn("http://192.168.42.190:8000", urlparse(playback_url).path)

    def test_library_stream_url_points_to_pi_file_endpoint(self) -> None:
        stream_url = build_library_stream_url(
            "http://192.168.42.190:8000",
            "Album One/song.mp3",
        )

        self.assertEqual(
            stream_url,
            "http://192.168.42.190:8000/api/library/file?path=Album+One%2Fsong.mp3",
        )


class SoundTouchCliClientTests(unittest.TestCase):
    def test_build_custom_radio_command_matches_working_cli_flow(self) -> None:
        command = SoundTouchCliClient(
            "soundtouch-cli",
            "192.168.42.101",
            "http://bose-controller.local",
        ).build_custom_radio_command(
            "Test MP3",
            "http://192.168.42.190:8000/api/library/file?path=song.mp3",
        )

        self.assertEqual(
            command,
            [
                "soundtouch-cli",
                "--host",
                "192.168.42.101",
                "source",
                "custom-radio",
                "--service-url",
                "http://bose-controller.local",
                "--name",
                "Test MP3",
                "--url",
                "http://192.168.42.190:8000/api/library/file?path=song.mp3",
            ],
        )

    @patch("thecakeisapi.bose.subprocess.run")
    def test_play_stream_runs_soundtouch_cli(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        request = SoundTouchCliClient(
            "soundtouch-cli",
            "192.168.42.101",
            "http://bose-controller.local/",
        ).play_stream(
            "Test MP3",
            "http://192.168.42.190:8000/api/library/file?path=song.mp3",
        )

        self.assertEqual(request.playback_url, None)
        self.assertEqual(
            request.stream_url,
            "http://192.168.42.190:8000/api/library/file?path=song.mp3",
        )
        run_mock.assert_called_once_with(
            [
                "soundtouch-cli",
                "--host",
                "192.168.42.101",
                "source",
                "custom-radio",
                "--service-url",
                "http://bose-controller.local",
                "--name",
                "Test MP3",
                "--url",
                "http://192.168.42.190:8000/api/library/file?path=song.mp3",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )

    @patch("thecakeisapi.bose.subprocess.run")
    def test_play_stream_reports_cli_failure_output(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="speaker not found",
        )

        with self.assertRaisesRegex(
            BosePlaybackError,
            "soundtouch-cli playback failed: speaker not found",
        ):
            SoundTouchCliClient(
                "soundtouch-cli",
                "192.168.42.101",
                "http://bose-controller.local",
            ).play_stream(
                "Test MP3",
                "http://192.168.42.190:8000/api/library/file?path=song.mp3",
            )

    def test_build_stop_command_uses_soundtouch_cli_play_stop(self) -> None:
        command = SoundTouchCliClient(
            "soundtouch-cli",
            "192.168.42.101",
            "http://bose-controller.local",
        ).build_stop_command()

        self.assertEqual(
            command,
            [
                "soundtouch-cli",
                "--host",
                "192.168.42.101",
                "play",
                "stop",
            ],
        )

    @patch("thecakeisapi.bose.subprocess.run")
    def test_stop_runs_soundtouch_cli_play_stop(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        SoundTouchCliClient(
            "soundtouch-cli",
            "192.168.42.101",
            "http://bose-controller.local",
        ).stop()

        run_mock.assert_called_once_with(
            [
                "soundtouch-cli",
                "--host",
                "192.168.42.101",
                "play",
                "stop",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )

    @patch("thecakeisapi.bose.subprocess.run")
    def test_stop_reports_cli_failure_output(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="stop failed",
        )

        with self.assertRaisesRegex(
            BosePlaybackError,
            "soundtouch-cli stop failed: stop failed",
        ):
            SoundTouchCliClient(
                "soundtouch-cli",
                "192.168.42.101",
                "http://bose-controller.local",
            ).stop()


class BoseNowPlayingTests(unittest.TestCase):
    def test_now_playing_confirmation_success(self) -> None:
        previous_status = parse_now_playing('<nowPlaying source="STANDBY"></nowPlaying>')
        client = FakeNowPlayingClient(
            [
                '<nowPlaying source="STANDBY"></nowPlaying>',
                '<nowPlaying source="CUSTOM_RADIO"><track>Test MP3</track></nowPlaying>',
            ],
        )

        status = client.wait_for_custom_radio(
            timeout_seconds=1,
            poll_interval_seconds=0.001,
            previous_status=previous_status,
        )

        self.assertIsNotNone(status)
        self.assertEqual(status.source, "CUSTOM_RADIO")

    def test_now_playing_confirmation_timeout(self) -> None:
        previous_status = parse_now_playing('<nowPlaying source="STANDBY"></nowPlaying>')
        client = FakeNowPlayingClient(['<nowPlaying source="STANDBY"></nowPlaying>'])

        status = client.wait_for_custom_radio(
            timeout_seconds=0,
            poll_interval_seconds=0.001,
            previous_status=previous_status,
        )

        self.assertIsNone(status)


class BosePlaybackStateTests(unittest.TestCase):
    def test_elapsed_seconds_uses_confirmed_start_timestamp(self) -> None:
        state = BosePlaybackState(
            state="playing",
            confirmed_start_timestamp=100.0,
            duration_seconds=10.0,
        )

        self.assertEqual(state.elapsed_seconds(now=104.5), 4.5)

    def test_auto_advance_when_duration_plus_buffer_reached(self) -> None:
        state = BosePlaybackState(
            state="playing",
            confirmed_start_timestamp=100.0,
            duration_seconds=10.0,
        )

        self.assertFalse(state.should_auto_advance(buffer_seconds=2.0, now=111.9))
        self.assertTrue(state.should_auto_advance(buffer_seconds=2.0, now=112.0))

    def test_stop_cancels_timer_state(self) -> None:
        state = BosePlaybackState(
            state="playing",
            confirmed_start_timestamp=100.0,
            duration_seconds=10.0,
        )

        state.stop()

        self.assertEqual(state.state, "stopped")
        self.assertIsNone(state.confirmed_start_timestamp)
        self.assertIsNone(state.elapsed_seconds(now=120.0))


class BoseAutoAdvanceTests(unittest.TestCase):
    def test_bose_auto_advance_starts_next_track(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [
                    QueueTrack(path="first.mp3", name="first.mp3"),
                    QueueTrack(path="second.mp3", name="second.mp3"),
                ],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = BosePlaybackState(
                track_path="first.mp3",
                track_name="first.mp3",
                state="playing",
                confirmed_start_timestamp=time.time() - 4,
                duration_seconds=1.0,
            )

            _sync_bose_playback(app)

            self.assertEqual(app.state.playback_queue.current().path, "second.mp3")
            self.assertEqual(app.state.bose_client.played_names, ["second.mp3"])

    def test_bose_repeat_replays_current_track(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [QueueTrack(path="first.mp3", name="first.mp3")],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.repeat_track = True
            app.state.bose_playback_state = BosePlaybackState(
                track_path="first.mp3",
                track_name="first.mp3",
                state="playing",
                confirmed_start_timestamp=time.time() - 4,
                duration_seconds=1.0,
            )

            _sync_bose_playback(app)

            self.assertEqual(app.state.playback_queue.current().path, "first.mp3")
            self.assertEqual(app.state.bose_client.played_names, ["first.mp3"])

    def test_bose_stop_cancels_timer_state(self) -> None:
        with temp_music_app() as app:
            app.state.bose_playback_state = BosePlaybackState(
                state="playing",
                confirmed_start_timestamp=time.time() - 4,
                duration_seconds=1.0,
            )

            _stop_bose_playback(app)

            self.assertTrue(app.state.bose_client.stopped)
            self.assertEqual(app.state.bose_playback_state.state, "stopped")
            self.assertIsNone(app.state.bose_playback_state.confirmed_start_timestamp)


class FakeNowPlayingClient(BoseNowPlayingClient):
    def __init__(self, raw_statuses: list[str]) -> None:
        self.raw_statuses = raw_statuses

    def fetch_status(self) -> BoseNowPlayingStatus:
        if len(self.raw_statuses) > 1:
            return parse_now_playing(self.raw_statuses.pop(0))
        return parse_now_playing(self.raw_statuses[0])


class FakeBoseClient:
    def __init__(self) -> None:
        self.played_names: list[str] = []
        self.stopped = False

    def play_stream(self, name: str, stream_url: str) -> BosePlaybackRequest:
        self.played_names.append(name)
        return BosePlaybackRequest(stream_url=stream_url, command=["fake"])

    def stop(self) -> None:
        self.stopped = True


class temp_music_app:
    def __enter__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        music_root = Path(self.temp_dir.name)
        (music_root / "first.mp3").write_bytes(b"\xff\xfb\x90d" + (b"\0" * 1000))
        (music_root / "second.mp3").write_bytes(b"\xff\xfb\x90d" + (b"\0" * 1000))
        self.app = create_app(
            Settings(
                music_root=music_root,
                bose_speaker_ip="192.168.42.101",
                aftertouch_base_url="http://bose-controller.local",
                public_base_url="http://192.168.42.190:8000",
                bose_start_confirm_timeout_seconds=0,
                bose_start_poll_interval_seconds=0.001,
                bose_auto_advance_buffer_seconds=0.5,
            ),
        )
        self.app.state.playback_monitor_stop.set()
        self.app.state.bose_client = FakeBoseClient()
        self.app.state.bose_now_playing_client = FakeNowPlayingClient(
            ['<nowPlaying source="CUSTOM_RADIO"></nowPlaying>'],
        )
        return self.app

    def __exit__(self, *args):
        self.app.state.playback_monitor_stop.set()
        self.temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
