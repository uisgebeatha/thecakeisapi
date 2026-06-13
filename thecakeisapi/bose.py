import base64
import subprocess
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


class BosePlaybackError(Exception):
    """Raised when Bose or AfterTouch playback cannot be started."""


@dataclass(frozen=True)
class BosePlaybackRequest:
    stream_url: str
    playback_url: str | None = None
    command: list[str] | None = None


class AfterTouchClient:
    def __init__(self, base_url: str, timeout_seconds: float = 8) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds

    def build_custom_playback_url(self, stream_url: str) -> str:
        encoded_stream_url = base64.b64encode(stream_url.encode("utf-8")).decode("ascii")
        return urljoin(self.base_url, f"custom/v1/playback/{encoded_stream_url}")

    def play_stream(self, stream_url: str) -> BosePlaybackRequest:
        playback_url = self.build_custom_playback_url(stream_url)
        request = Request(playback_url, method="GET")

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status >= 400:
                    raise BosePlaybackError(
                        f"AfterTouch returned HTTP {response.status}",
                    )
        except URLError as error:
            raise BosePlaybackError(f"AfterTouch playback request failed: {error}") from error

        return BosePlaybackRequest(
            stream_url=stream_url,
            playback_url=playback_url,
        )


class SoundTouchCliClient:
    def __init__(
        self,
        command: str,
        speaker_ip: str,
        service_url: str,
        timeout_seconds: float = 15,
    ) -> None:
        self.command = command
        self.speaker_ip = speaker_ip
        self.service_url = service_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def build_custom_radio_command(self, name: str, stream_url: str) -> list[str]:
        return [
            self.command,
            "--host",
            self.speaker_ip,
            "source",
            "custom-radio",
            "--service-url",
            self.service_url,
            "--name",
            name,
            "--url",
            stream_url,
        ]

    def play_stream(self, name: str, stream_url: str) -> BosePlaybackRequest:
        command = self.build_custom_radio_command(name, stream_url)

        try:
            completed_process = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as error:
            raise BosePlaybackError(
                f"soundtouch-cli command was not found: {self.command}",
            ) from error
        except subprocess.TimeoutExpired as error:
            raise BosePlaybackError("soundtouch-cli command timed out") from error
        except OSError as error:
            raise BosePlaybackError(f"soundtouch-cli command failed: {error}") from error

        if completed_process.returncode != 0:
            error_output = completed_process.stderr.strip() or completed_process.stdout.strip()
            if not error_output:
                error_output = f"exit code {completed_process.returncode}"
            raise BosePlaybackError(f"soundtouch-cli playback failed: {error_output}")

        return BosePlaybackRequest(
            stream_url=stream_url,
            command=command,
        )


def build_library_stream_url(public_base_url: str, library_path: str) -> str:
    query = urlencode({"path": library_path})
    return urljoin(public_base_url.rstrip("/") + "/", f"api/library/file?{query}")
