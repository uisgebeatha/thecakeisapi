import base64
import unittest
from urllib.parse import urlparse

from thecakeisapi.bose import AfterTouchClient, build_library_stream_url


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


if __name__ == "__main__":
    unittest.main()
