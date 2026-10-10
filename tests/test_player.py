import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from thecakeisapi.player import MpvPlayer


class MpvPlayerSourceTests(unittest.TestCase):
    def test_http_and_https_urls_reach_mpv_unchanged(self) -> None:
        for stream_url in (
            "http://radio.example/stream",
            "https://radio.example/live?format=mp3&quality=high",
        ):
            with self.subTest(stream_url=stream_url):
                player = MpvPlayer("mpv", Path("/tmp/thecakeisapi-test.sock"))
                process = Mock()
                process.poll.return_value = None
                process.pid = 123

                with (
                    patch("thecakeisapi.player.subprocess.Popen", return_value=process) as popen,
                    patch.object(player, "_read_property", return_value=None),
                ):
                    status = player.play(stream_url)

                command = popen.call_args.args[0]
                self.assertEqual(command[-1], stream_url)
                self.assertEqual(status["source"], stream_url)
                self.assertIsNone(status["path"])
                self.assertIsInstance(player._current_source, str)

    def test_local_path_status_remains_compatible(self) -> None:
        audio_path = Path("/mnt/music/Album/song.mp3")
        player = MpvPlayer("mpv", Path("/tmp/thecakeisapi-test.sock"))
        process = Mock()
        process.poll.return_value = None
        process.pid = 123

        with (
            patch("thecakeisapi.player.subprocess.Popen", return_value=process) as popen,
            patch.object(player, "_read_property", return_value=None),
        ):
            status = player.play(audio_path)

        self.assertEqual(popen.call_args.args[0][-1], str(audio_path))
        self.assertEqual(status["path"], str(audio_path))
        self.assertEqual(status["source"], str(audio_path))


if __name__ == "__main__":
    unittest.main()
