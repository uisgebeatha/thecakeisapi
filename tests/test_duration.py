import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thecakeisapi.duration import audio_duration_seconds


class DurationDetectionTests(unittest.TestCase):
    @patch("thecakeisapi.duration.subprocess.run")
    def test_uses_ffprobe_duration_when_available(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"format": {"duration": "123.456"}}',
            stderr="",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "song.mp3"
            audio_path.write_bytes(b"not real audio")

            self.assertEqual(audio_duration_seconds(audio_path), 123.456)

        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.args[0][0], "ffprobe")
        self.assertIn("format=duration", run_mock.call_args.args[0])

    @patch("thecakeisapi.duration.subprocess.run")
    def test_falls_back_to_mp3_estimator_when_ffprobe_is_unavailable(self, run_mock) -> None:
        run_mock.side_effect = FileNotFoundError

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "song.mp3"
            audio_path.write_bytes(_mp3_frames([(9, 39)]))

            duration = audio_duration_seconds(audio_path)

        self.assertIsNotNone(duration)
        self.assertAlmostEqual(duration, 1.0, delta=0.1)

    @patch("thecakeisapi.duration.subprocess.run")
    def test_mp3_fallback_counts_variable_bitrate_frames(self, run_mock) -> None:
        run_mock.side_effect = FileNotFoundError

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "variable.mp3"
            audio_path.write_bytes(_mp3_frames([(9, 20), (14, 20)]))

            duration = audio_duration_seconds(audio_path)

        self.assertIsNotNone(duration)
        self.assertAlmostEqual(duration, 40 * 1152 / 44100, places=3)

    @patch("thecakeisapi.duration.subprocess.run")
    def test_falls_back_to_flac_parser_when_ffprobe_fails(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="ffprobe error",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "song.flac"
            audio_path.write_bytes(_minimal_flac_streaminfo(sample_rate=44100, total_samples=88200))

            self.assertEqual(audio_duration_seconds(audio_path), 2.0)

    @patch("thecakeisapi.duration.subprocess.run")
    def test_returns_none_when_ffprobe_and_fallback_fail(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"format": {"duration": "0"}}',
            stderr="",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "song.mp3"
            audio_path.write_bytes(b"not real audio")

            self.assertIsNone(audio_duration_seconds(audio_path))


def _minimal_flac_streaminfo(sample_rate: int, total_samples: int) -> bytes:
    streaminfo = bytearray(34)
    packed_values = (sample_rate << 44) | total_samples
    streaminfo[10:18] = packed_values.to_bytes(8, "big")
    metadata_header = bytes([0x80, 0x00, 0x00, len(streaminfo)])
    return b"fLaC" + metadata_header + bytes(streaminfo)


def _mp3_frames(groups: list[tuple[int, int]]) -> bytes:
    frames = bytearray()
    for bitrate_index, count in groups:
        header_value = (
            (0x7FF << 21)
            | (0b11 << 19)
            | (0b01 << 17)
            | (1 << 16)
            | (bitrate_index << 12)
        )
        header = header_value.to_bytes(4, "big")
        bitrate_kbps = {
            9: 128,
            14: 320,
        }[bitrate_index]
        frame_length = (144000 * bitrate_kbps) // 44100
        frame = header + bytes(frame_length - len(header))
        frames.extend(frame * count)
    return bytes(frames)


if __name__ == "__main__":
    unittest.main()
