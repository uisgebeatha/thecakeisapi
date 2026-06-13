import base64
import subprocess
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from thecakeisapi.bose import (
    AfterTouchClient,
    BosePlaybackError,
    SoundTouchCliClient,
    build_library_stream_url,
)


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


if __name__ == "__main__":
    unittest.main()
