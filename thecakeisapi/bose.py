import base64
import subprocess
import time
from dataclasses import dataclass
from xml.etree import ElementTree
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


@dataclass(frozen=True)
class BoseNowPlayingStatus:
    source: str | None
    play_status: str | None
    raw_text: str

    @property
    def appears_to_be_custom_radio(self) -> bool:
        normalized_text = self.raw_text.upper()
        normalized_source = (self.source or "").upper()
        if "STANDBY" in normalized_source or "STANDBY" in normalized_text:
            return False

        custom_markers = (
            "CUSTOM",
            "INTERNET_RADIO",
            "INTERNET RADIO",
            "LOCAL_INTERNET_RADIO",
            "LOCAL INTERNET RADIO",
            "RADIO",
        )
        return any(
            marker in normalized_source or marker in normalized_text
            for marker in custom_markers
        )

    @property
    def appears_to_be_stopped(self) -> bool:
        normalized_source = (self.source or "").upper()
        normalized_play_status = (self.play_status or "").upper()
        normalized_text = self.raw_text.upper()
        stopped_markers = ("STANDBY", "STOP_STATE", "STOPPED")
        return any(
            marker in normalized_source
            or marker in normalized_play_status
            or marker in normalized_text
            for marker in stopped_markers
        )

    @property
    def appears_to_be_standby(self) -> bool:
        return (
            "STANDBY" in (self.source or "").upper()
            or "STANDBY" in self.raw_text.upper()
        )


@dataclass
class BosePlaybackState:
    track_path: str | None = None
    track_name: str | None = None
    state: str = "stopped"
    start_timestamp: float | None = None
    confirmed_start_timestamp: float | None = None
    paused_elapsed_seconds: float | None = None
    duration_seconds: float | None = None
    stream_url: str | None = None
    command: list[str] | None = None
    warning: str | None = None
    last_status_poll_monotonic: float | None = None
    last_confirmed_status_timestamp: float | None = None
    status_poll_failures: int = 0

    def elapsed_seconds(self, now: float | None = None) -> float | None:
        if self.state == "paused":
            return self.paused_elapsed_seconds

        if self.confirmed_start_timestamp is None:
            return None

        current_time = time.time() if now is None else now
        return max(0.0, current_time - self.confirmed_start_timestamp)

    def should_auto_advance(self, buffer_seconds: float, now: float | None = None) -> bool:
        if self.state != "playing" or self.duration_seconds is None:
            return False

        elapsed_seconds = self.elapsed_seconds(now)
        if elapsed_seconds is None:
            return False

        return elapsed_seconds >= self.duration_seconds + buffer_seconds

    def stop(self) -> None:
        self.state = "stopped"
        self.confirmed_start_timestamp = None
        self.paused_elapsed_seconds = None
        self.warning = None
        self.last_status_poll_monotonic = None
        self.status_poll_failures = 0

    def status_poll_due(
        self,
        interval_seconds: float,
        now_monotonic: float | None = None,
    ) -> bool:
        current_time = time.monotonic() if now_monotonic is None else now_monotonic
        if self.last_status_poll_monotonic is None:
            return True
        return current_time - self.last_status_poll_monotonic >= interval_seconds

    def record_status_poll_started(self, now_monotonic: float | None = None) -> None:
        self.last_status_poll_monotonic = (
            time.monotonic() if now_monotonic is None else now_monotonic
        )

    def record_status_poll_success(self, now_timestamp: float | None = None) -> None:
        self.last_confirmed_status_timestamp = (
            time.time() if now_timestamp is None else now_timestamp
        )
        self.status_poll_failures = 0

    def record_status_poll_failure(self) -> int:
        self.status_poll_failures += 1
        return self.status_poll_failures

    def externally_stopped(self, reason: str) -> None:
        self.state = "stopped"
        self.confirmed_start_timestamp = None
        self.paused_elapsed_seconds = None
        self.warning = reason

    def pause(self, now: float | None = None) -> None:
        if self.state != "playing":
            return

        self.paused_elapsed_seconds = self.elapsed_seconds(now)
        self.state = "paused"

    def resume(self, now: float | None = None) -> None:
        if self.state != "paused":
            return

        current_time = time.time() if now is None else now
        elapsed_seconds = self.paused_elapsed_seconds or 0.0
        self.confirmed_start_timestamp = current_time - elapsed_seconds
        self.paused_elapsed_seconds = None
        self.state = "playing"

    def resume_from_start(self, now: float | None = None) -> None:
        if self.state != "paused":
            return

        current_time = time.time() if now is None else now
        self.confirmed_start_timestamp = current_time
        self.paused_elapsed_seconds = None
        self.state = "playing"
        self.warning = "Bose resume restarts playback; timer reset"
        self.last_status_poll_monotonic = None
        self.status_poll_failures = 0

    def ended(self) -> None:
        self.state = "ended"

    def error(self, message: str) -> None:
        self.state = "error"
        self.warning = message


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
        service_url: str | None,
        timeout_seconds: float = 15,
    ) -> None:
        self.command = command
        self.speaker_ip = speaker_ip
        self.service_url = service_url.rstrip("/") if service_url else None
        self.timeout_seconds = timeout_seconds

    def build_custom_radio_command(self, name: str, stream_url: str) -> list[str]:
        if not self.service_url:
            raise BosePlaybackError("aftertouch_base_url is not configured")

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

    def build_stop_command(self) -> list[str]:
        return [
            self.command,
            "--host",
            self.speaker_ip,
            "play",
            "stop",
        ]

    def build_pause_command(self) -> list[str]:
        return self._build_play_command("pause")

    def build_resume_command(self) -> list[str]:
        return self._build_play_command("start")

    def build_now_command(self) -> list[str]:
        return self._build_play_command("now")

    def _build_play_command(self, action: str) -> list[str]:
        return [
            self.command,
            "--host",
            self.speaker_ip,
            "play",
            action,
        ]

    def play_stream(self, name: str, stream_url: str) -> BosePlaybackRequest:
        command = self.build_custom_radio_command(name, stream_url)
        self._run_command(command, "playback")

        return BosePlaybackRequest(
            stream_url=stream_url,
            command=command,
        )

    def stop(self) -> None:
        self._run_command(self.build_stop_command(), "stop")

    def pause(self) -> None:
        self._run_command(self.build_pause_command(), "pause")

    def resume(self) -> None:
        self._run_command(self.build_resume_command(), "resume")

    def now(self) -> str:
        return self._run_command(self.build_now_command(), "now")

    def _run_command(self, command: list[str], action: str) -> str:
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
            raise BosePlaybackError(f"soundtouch-cli {action} failed: {error_output}")

        return completed_process.stdout.strip()


class BoseNowPlayingClient:
    def __init__(
        self,
        speaker_ip: str,
        api_port: int = 8090,
        timeout_seconds: float = 3,
    ) -> None:
        self.now_playing_url = f"http://{speaker_ip}:{api_port}/now_playing"
        self.timeout_seconds = timeout_seconds

    def fetch_status(self) -> BoseNowPlayingStatus:
        request = Request(self.now_playing_url, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
        except (URLError, OSError) as error:
            raise BosePlaybackError(f"Bose now_playing request failed: {error}") from error

        return parse_now_playing(body)

    def wait_for_custom_radio(
        self,
        timeout_seconds: float,
        poll_interval_seconds: float,
        previous_status: BoseNowPlayingStatus | None = None,
    ) -> BoseNowPlayingStatus | None:
        deadline = time.monotonic() + timeout_seconds
        previous_raw_text = previous_status.raw_text if previous_status else None
        previous_was_standby = (
            previous_status is not None
            and "STANDBY" in previous_status.raw_text.upper()
        )

        while True:
            status = self.fetch_status()
            changed = previous_raw_text is None or status.raw_text != previous_raw_text
            if status.appears_to_be_custom_radio and (changed or not previous_was_standby):
                return status

            if time.monotonic() >= deadline:
                return None

            time.sleep(poll_interval_seconds)


def parse_now_playing(raw_text: str) -> BoseNowPlayingStatus:
    try:
        root = ElementTree.fromstring(raw_text)
    except ElementTree.ParseError:
        return BoseNowPlayingStatus(source=None, play_status=None, raw_text=raw_text)

    source = root.attrib.get("source")
    if not source:
        content_item = root.find(".//ContentItem")
        if content_item is not None:
            source = content_item.attrib.get("source")

    play_status = root.attrib.get("playStatus") or root.findtext(".//playStatus")
    return BoseNowPlayingStatus(
        source=source,
        play_status=play_status,
        raw_text=raw_text,
    )


def build_library_stream_url(public_base_url: str, library_path: str) -> str:
    query = urlencode({"path": library_path})
    return urljoin(public_base_url.rstrip("/") + "/", f"api/library/file?{query}")
