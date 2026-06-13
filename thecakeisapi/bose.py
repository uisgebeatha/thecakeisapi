from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


class BosePlaybackError(Exception):
    """Raised when Bose or AfterTouch playback cannot be started."""


@dataclass(frozen=True)
class BosePlaybackRequest:
    stream_url: str
    playback_url: str


class AfterTouchClient:
    def __init__(self, base_url: str, timeout_seconds: float = 8) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds

    def build_custom_playback_url(self, stream_url: str) -> str:
        encoded_stream_url = quote(stream_url, safe="")
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


def build_library_stream_url(public_base_url: str, library_path: str) -> str:
    query = urlencode({"path": library_path})
    return urljoin(public_base_url.rstrip("/") + "/", f"api/library/file?{query}")
