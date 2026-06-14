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
    _play_bose_track,
    _play_track,
    _playback_status,
    _pause_bose_playback,
    _resume_bose_playback,
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

    def test_build_pause_command_uses_soundtouch_cli_play_pause(self) -> None:
        command = SoundTouchCliClient(
            "soundtouch-cli",
            "192.168.42.101",
            "http://bose-controller.local",
        ).build_pause_command()

        self.assertEqual(
            command,
            [
                "soundtouch-cli",
                "--host",
                "192.168.42.101",
                "play",
                "pause",
            ],
        )

    def test_build_resume_command_uses_soundtouch_cli_play_start(self) -> None:
        command = SoundTouchCliClient(
            "soundtouch-cli",
            "192.168.42.101",
            "http://bose-controller.local",
        ).build_resume_command()

        self.assertEqual(
            command,
            [
                "soundtouch-cli",
                "--host",
                "192.168.42.101",
                "play",
                "start",
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

    @patch("thecakeisapi.bose.subprocess.run")
    def test_pause_runs_soundtouch_cli_play_pause(self, run_mock) -> None:
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
        ).pause()

        run_mock.assert_called_once_with(
            [
                "soundtouch-cli",
                "--host",
                "192.168.42.101",
                "play",
                "pause",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )

    @patch("thecakeisapi.bose.subprocess.run")
    def test_resume_runs_soundtouch_cli_play_start(self, run_mock) -> None:
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
        ).resume()

        run_mock.assert_called_once_with(
            [
                "soundtouch-cli",
                "--host",
                "192.168.42.101",
                "play",
                "start",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )


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

    def test_pause_freezes_elapsed_time(self) -> None:
        state = BosePlaybackState(
            state="playing",
            confirmed_start_timestamp=100.0,
            duration_seconds=10.0,
        )

        state.pause(now=104.0)

        self.assertEqual(state.state, "paused")
        self.assertEqual(state.elapsed_seconds(now=120.0), 4.0)

    def test_resume_continues_from_paused_elapsed_time(self) -> None:
        state = BosePlaybackState(
            state="paused",
            confirmed_start_timestamp=100.0,
            paused_elapsed_seconds=4.0,
            duration_seconds=10.0,
        )

        state.resume(now=120.0)

        self.assertEqual(state.state, "playing")
        self.assertEqual(state.confirmed_start_timestamp, 116.0)
        self.assertEqual(state.elapsed_seconds(now=122.0), 6.0)

    def test_resume_from_start_resets_untrusted_elapsed_time(self) -> None:
        state = BosePlaybackState(
            state="paused",
            confirmed_start_timestamp=100.0,
            paused_elapsed_seconds=4.0,
            duration_seconds=10.0,
        )

        state.resume_from_start(now=120.0)

        self.assertEqual(state.state, "playing")
        self.assertEqual(state.confirmed_start_timestamp, 120.0)
        self.assertIsNone(state.paused_elapsed_seconds)
        self.assertEqual(state.elapsed_seconds(now=120.5), 0.5)
        self.assertEqual(
            state.warning,
            "Bose resume position could not be verified; timer reset",
        )

    def test_auto_advance_does_not_fire_while_paused(self) -> None:
        state = BosePlaybackState(
            state="paused",
            confirmed_start_timestamp=100.0,
            paused_elapsed_seconds=20.0,
            duration_seconds=10.0,
        )

        self.assertFalse(state.should_auto_advance(buffer_seconds=1.0, now=130.0))


class PlaybackCleanupTests(unittest.TestCase):
    def test_default_bose_auto_advance_buffer_is_one_second(self) -> None:
        self.assertEqual(Settings().bose_auto_advance_buffer_seconds, 1.0)

    def test_bose_status_survives_refresh_equivalent_status_read(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [QueueTrack(path="first.mp3", name="first.mp3")],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = BosePlaybackState(
                track_path="first.mp3",
                track_name="first.mp3",
                state="playing",
                confirmed_start_timestamp=time.time() - 2,
                duration_seconds=10.0,
            )

            status = _playback_status(app)

            self.assertEqual(status["active_output"], "bose")
            self.assertEqual(status["state"], "playing")
            self.assertEqual(status["now_playing"]["path"], "first.mp3")
            self.assertGreaterEqual(status["elapsed_seconds"], 2.0)

    def test_bose_paused_status_survives_refresh_equivalent_status_read(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [QueueTrack(path="first.mp3", name="first.mp3")],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = BosePlaybackState(
                track_path="first.mp3",
                track_name="first.mp3",
                state="paused",
                confirmed_start_timestamp=time.time() - 10,
                paused_elapsed_seconds=3.0,
                duration_seconds=10.0,
            )

            status = _playback_status(app)

            self.assertEqual(status["active_output"], "bose")
            self.assertEqual(status["state"], "paused")
            self.assertTrue(status["paused"])
            self.assertEqual(status["elapsed_seconds"], 3.0)

    def test_starting_bose_stops_local_playback_first(self) -> None:
        with temp_music_app() as app:
            local_player = FakeLocalPlayer()
            app.state.local_player = local_player

            _play_bose_track(app, QueueTrack(path="first.mp3", name="first.mp3"))

            self.assertEqual(local_player.stop_count, 1)
            self.assertEqual(app.state.bose_client.played_names, ["first.mp3"])

    def test_starting_local_playback_stops_active_bose_first(self) -> None:
        with temp_music_app() as app:
            local_player = FakeLocalPlayer()
            app.state.local_player = local_player
            app.state.active_output = "bose"
            app.state.bose_playback_state = BosePlaybackState(
                state="playing",
                confirmed_start_timestamp=time.time() - 2,
                duration_seconds=10.0,
            )

            _play_track(app, QueueTrack(path="first.mp3", name="first.mp3"))

            self.assertTrue(app.state.bose_client.stopped)
            self.assertEqual(local_player.played_paths, ["first.mp3"])


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

    def test_bose_pause_and_resume_update_timer_state(self) -> None:
        with temp_music_app() as app:
            app.state.bose_playback_state = BosePlaybackState(
                state="playing",
                confirmed_start_timestamp=time.time() - 3,
                duration_seconds=10.0,
            )

            _pause_bose_playback(app)
            paused_elapsed_seconds = app.state.bose_playback_state.paused_elapsed_seconds
            _resume_bose_playback(app)

            self.assertTrue(app.state.bose_client.paused)
            self.assertTrue(app.state.bose_client.resumed)
            self.assertEqual(app.state.bose_playback_state.state, "playing")
            self.assertIsNotNone(paused_elapsed_seconds)
            self.assertLess(app.state.bose_playback_state.elapsed_seconds(), 0.2)
            self.assertIsNone(app.state.bose_playback_state.paused_elapsed_seconds)
            self.assertEqual(
                app.state.bose_playback_state.warning,
                "Bose resume position could not be verified; timer reset",
            )


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
        self.paused = False
        self.resumed = False

    def play_stream(self, name: str, stream_url: str) -> BosePlaybackRequest:
        self.played_names.append(name)
        return BosePlaybackRequest(stream_url=stream_url, command=["fake"])

    def stop(self) -> None:
        self.stopped = True

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.resumed = True


class FakeLocalPlayer:
    def __init__(self) -> None:
        self.stop_count = 0
        self.played_paths: list[str] = []

    def stop(self):
        self.stop_count += 1
        return self.status()

    def play(self, audio_path: Path):
        self.played_paths.append(audio_path.name)
        return self.status()

    def status(self):
        return {
            "backend": "mpv",
            "state": "stopped",
            "process_id": None,
            "elapsed_seconds": None,
            "duration_seconds": None,
            "paused": False,
        }


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
