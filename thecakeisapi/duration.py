import json
import subprocess
from pathlib import Path


MP3_BITRATES = {
    "V1L3": {
        1: 32,
        2: 40,
        3: 48,
        4: 56,
        5: 64,
        6: 80,
        7: 96,
        8: 112,
        9: 128,
        10: 160,
        11: 192,
        12: 224,
        13: 256,
        14: 320,
    },
    "V2L3": {
        1: 8,
        2: 16,
        3: 24,
        4: 32,
        5: 40,
        6: 48,
        7: 56,
        8: 64,
        9: 80,
        10: 96,
        11: 112,
        12: 128,
        13: 144,
        14: 160,
    },
}

MP3_SAMPLE_RATES = {
    0b11: {0: 44100, 1: 48000, 2: 32000},
    0b10: {0: 22050, 1: 24000, 2: 16000},
    0b00: {0: 11025, 1: 12000, 2: 8000},
}


def audio_duration_seconds(path: Path) -> float | None:
    ffprobe_duration = _ffprobe_duration_seconds(path)
    if ffprobe_duration is not None:
        return ffprobe_duration

    return _estimated_duration_seconds(path)


def _ffprobe_duration_seconds(path: Path) -> float | None:
    try:
        completed_process = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None

    if completed_process.returncode != 0:
        return None

    try:
        duration_value = json.loads(completed_process.stdout).get("format", {}).get("duration")
        duration_seconds = float(duration_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if duration_seconds <= 0:
        return None

    return duration_seconds


def _estimated_duration_seconds(path: Path) -> float | None:
    suffix = path.suffix.casefold()
    if suffix == ".flac":
        return _flac_duration_seconds(path)
    if suffix == ".mp3":
        return _mp3_duration_seconds(path)
    return None


def _flac_duration_seconds(path: Path) -> float | None:
    with path.open("rb") as audio_file:
        if audio_file.read(4) != b"fLaC":
            return None

        while True:
            header = audio_file.read(4)
            if len(header) < 4:
                return None

            is_last_block = bool(header[0] & 0x80)
            block_type = header[0] & 0x7F
            block_length = int.from_bytes(header[1:4], "big")
            block_data = audio_file.read(block_length)

            if block_type == 0 and len(block_data) >= 18:
                packed_values = int.from_bytes(block_data[10:18], "big")
                sample_rate = (packed_values >> 44) & 0xFFFFF
                total_samples = packed_values & 0xFFFFFFFFF
                if sample_rate > 0 and total_samples > 0:
                    return total_samples / sample_rate
                return None

            if is_last_block:
                return None


def _mp3_duration_seconds(path: Path) -> float | None:
    file_size = path.stat().st_size
    with path.open("rb") as audio_file:
        start_offset = _skip_id3v2_tag(audio_file)
        audio_file.seek(start_offset)
        search_data = audio_file.read(4096)

    for index in range(max(0, len(search_data) - 4)):
        header = int.from_bytes(search_data[index : index + 4], "big")
        bitrate_kbps = _mp3_bitrate_kbps(header)
        if bitrate_kbps is None:
            continue

        audio_bytes = max(0, file_size - start_offset - index)
        if audio_bytes == 0:
            return None

        return audio_bytes / ((bitrate_kbps * 1000) / 8)

    return None


def _skip_id3v2_tag(audio_file) -> int:
    header = audio_file.read(10)
    if len(header) < 10 or header[:3] != b"ID3":
        return 0

    tag_size = (
        (header[6] << 21)
        | (header[7] << 14)
        | (header[8] << 7)
        | header[9]
    )
    return 10 + tag_size


def _mp3_bitrate_kbps(header: int) -> int | None:
    if ((header >> 21) & 0x7FF) != 0x7FF:
        return None

    version = (header >> 19) & 0x03
    layer = (header >> 17) & 0x03
    bitrate_index = (header >> 12) & 0x0F
    sample_rate_index = (header >> 10) & 0x03

    if version == 0b01 or layer != 0b01:
        return None

    if bitrate_index == 0 or bitrate_index == 0x0F:
        return None

    if sample_rate_index == 0x03:
        return None

    bitrate_key = "V1L3" if version == 0b11 else "V2L3"
    if sample_rate_index not in MP3_SAMPLE_RATES[version]:
        return None

    return MP3_BITRATES[bitrate_key].get(bitrate_index)
