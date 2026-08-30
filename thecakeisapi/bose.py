import base64
import binascii
import subprocess
import time
from dataclasses import dataclass
from xml.etree import ElementTree
from urllib.error import URLError
from urllib.parse import unquote, urlencode, urljoin
from urllib.request import Request, urlopen


class BosePlaybackError(Exception):
    """Raised when Bose or AfterTouch playback cannot be started."""


@dataclass(frozen=True)
class BosePlaybackRequest:
    stream_url: str
    playback_url: str | None = None
    command: list[str] | None = None


@dataclass(frozen=True)
class BosePreset:
    id: int
    display_name: str | None
    source: str | None
    available: bool
    content_type: str | None = None
    location: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "source": self.source,
            "available": self.available,
        }


@dataclass(frozen=True)
class BoseNowPlayingStatus:
    source: str | None
    play_status: str | None
    track_name: str | None
    raw_text: str
    content_location: str | None = None
    source_account: str | None = None
    content_type: str | None = None
    station_location: str | None = None
    artist: str | None = None
    album: str | None = None
    track: str | None = None
    station_name: str | None = None
    item_name: str | None = None

    @property
    def display_name(self) -> str | None:
        return self.track or self.station_name or self.item_name or self.source_label

    @property
    def source_label(self) -> str | None:
        normalized_source = (self.source or "").upper()
        known_labels = {
            "AUX": "AUX",
            "LOCAL_INTERNET_RADIO": "Internet Radio",
            "INTERNET_RADIO": "Internet Radio",
            "CUSTOM_RADIO": "Custom Radio",
            "TUNEIN": "TuneIn",
        }
        if normalized_source in known_labels:
            return known_labels[normalized_source]
        if not self.source:
            return None
        return self.source.replace("_", " ").title()

    def matches_stream_url(self, expected_stream_url: str) -> bool:
        for location in (self.content_location, self.station_location):
            if not location:
                continue
            if location == expected_stream_url:
                return True
            if decode_custom_playback_stream_url(location) == expected_stream_url:
                return True
        return False

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

    @property
    def appears_to_be_invalid_source(self) -> bool:
        return (
            "INVALID_SOURCE" in (self.source or "").upper()
            or "INVALID_SOURCE" in self.raw_text.upper()
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
    ownership_stream_url: str | None = None
    ownership_confirmed: bool = False
    external_playback_active: bool = False
    external_display_name: str | None = None
    external_source: str | None = None

    @property
    def has_app_ownership_context(self) -> bool:
        return self.ownership_stream_url is not None

    def confirm_ownership(self) -> None:
        if self.ownership_stream_url is not None:
            self.ownership_confirmed = True
            self.external_playback_active = False
            self.external_display_name = None
            self.external_source = None

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
        self.ownership_stream_url = None
        self.ownership_confirmed = False
        self.external_playback_active = False
        self.external_display_name = None
        self.external_source = None

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
        self.ownership_stream_url = None
        self.ownership_confirmed = False
        self.external_playback_active = False
        self.external_display_name = None
        self.external_source = None

    def externally_active(
        self,
        reason: str,
        display_name: str | None = None,
        source: str | None = None,
    ) -> None:
        self.externally_stopped(reason)
        self.external_playback_active = True
        self.external_display_name = display_name
        self.external_source = source

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
        self.ownership_stream_url = None
        self.ownership_confirmed = False

    def error(self, message: str) -> None:
        self.state = "error"
        self.warning = message
        self.ownership_stream_url = None
        self.ownership_confirmed = False


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
        self.presets_url = f"http://{speaker_ip}:{api_port}/presets"
        self.key_url = f"http://{speaker_ip}:{api_port}/key"
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

    def fetch_presets(self) -> list[BosePreset]:
        request = Request(self.presets_url, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
        except (URLError, OSError) as error:
            raise BosePlaybackError(f"Bose presets request failed: {error}") from error

        return parse_presets(body)

    def select_preset(self, preset_id: int) -> None:
        if preset_id not in range(1, 7):
            raise BosePlaybackError("Bose preset id must be between 1 and 6")

        key_name = f"PRESET_{preset_id}"
        for key_state in ("press", "release"):
            body = (
                f'<key state="{key_state}" sender="Gabbo">'
                f"{key_name}</key>"
            ).encode("utf-8")
            request = Request(
                self.key_url,
                data=body,
                headers={"Content-Type": "application/xml"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    response.read()
            except (URLError, OSError) as error:
                raise BosePlaybackError(
                    f"Bose preset {preset_id} activation failed: {error}",
                ) from error

    def wait_for_custom_radio(
        self,
        timeout_seconds: float,
        poll_interval_seconds: float,
        previous_status: BoseNowPlayingStatus | None = None,
        expected_stream_url: str | None = None,
    ) -> BoseNowPlayingStatus | None:
        deadline = time.monotonic() + timeout_seconds
        previous_raw_text = previous_status.raw_text if previous_status else None
        previous_was_standby = bool(
            previous_status and previous_status.appears_to_be_standby
        )
        previous_was_custom_radio = bool(
            previous_status and previous_status.appears_to_be_custom_radio
        )
        saw_source_transition = False

        while True:
            status = self.fetch_status()
            if expected_stream_url is not None:
                if (
                    status.appears_to_be_custom_radio
                    and status.matches_stream_url(expected_stream_url)
                ):
                    return status
                if time.monotonic() >= deadline:
                    return None
                time.sleep(poll_interval_seconds)
                continue

            source_changed = (
                previous_raw_text is not None
                and status.raw_text != previous_raw_text
                and not previous_was_custom_radio
            )
            track_changed = bool(
                previous_status
                and previous_status.track_name
                and status.track_name
                and previous_status.track_name != status.track_name
            )
            if status.appears_to_be_custom_radio and (
                previous_raw_text is None
                or previous_was_standby
                or source_changed
                or track_changed
                or saw_source_transition
            ):
                return status

            if previous_was_custom_radio and not status.appears_to_be_custom_radio:
                saw_source_transition = True

            if time.monotonic() >= deadline:
                return None

            time.sleep(poll_interval_seconds)


def parse_now_playing(raw_text: str) -> BoseNowPlayingStatus:
    try:
        root = ElementTree.fromstring(raw_text)
    except ElementTree.ParseError:
        return BoseNowPlayingStatus(
            source=None,
            play_status=None,
            track_name=None,
            raw_text=raw_text,
        )

    content_item = root.find(".//ContentItem")
    source = root.attrib.get("source")
    if not source and content_item is not None:
        source = content_item.attrib.get("source")

    play_status = root.attrib.get("playStatus") or root.findtext(".//playStatus")
    track = root.findtext(".//track")
    station_name = root.findtext(".//stationName")
    item_name = root.findtext(".//itemName")
    track_name = track or item_name
    return BoseNowPlayingStatus(
        source=source,
        play_status=play_status,
        track_name=track_name,
        raw_text=raw_text,
        content_location=(
            content_item.attrib.get("location") if content_item is not None else None
        ),
        source_account=(
            content_item.attrib.get("sourceAccount")
            if content_item is not None
            else None
        ),
        content_type=(
            content_item.attrib.get("type") if content_item is not None else None
        ),
        station_location=root.findtext(".//stationLocation"),
        artist=root.findtext(".//artist"),
        album=root.findtext(".//album"),
        track=track,
        station_name=station_name,
        item_name=item_name,
    )


def parse_presets(raw_text: str) -> list[BosePreset]:
    try:
        root = ElementTree.fromstring(raw_text)
    except ElementTree.ParseError as error:
        raise BosePlaybackError("Bose presets response was invalid XML") from error

    presets = {
        preset_id: BosePreset(
            id=preset_id,
            display_name=None,
            source=None,
            available=False,
        )
        for preset_id in range(1, 7)
    }

    for preset_element in root.iter():
        if _xml_local_name(preset_element.tag) != "preset":
            continue

        try:
            preset_id = int(preset_element.attrib.get("id", ""))
        except ValueError:
            continue
        if preset_id not in presets:
            continue

        content_item = next(
            (
                element
                for element in preset_element.iter()
                if _xml_local_name(element.tag) == "ContentItem"
            ),
            None,
        )
        if content_item is None:
            continue

        item_name = next(
            (
                _clean_xml_text(element.text)
                for element in content_item.iter()
                if _xml_local_name(element.tag) == "itemName"
            ),
            None,
        )
        source = _clean_xml_text(content_item.attrib.get("source"))
        content_type = _clean_xml_text(content_item.attrib.get("type"))
        location = _clean_xml_text(content_item.attrib.get("location"))
        source_is_valid = (source or "").upper() not in {
            "",
            "INVALID_SOURCE",
            "STANDBY",
        }
        available = source_is_valid and bool(item_name or location)
        parsed_preset = BosePreset(
            id=preset_id,
            display_name=item_name if available else None,
            source=source if available else None,
            available=available,
            content_type=content_type if available else None,
            location=location if available else None,
        )
        if parsed_preset.available or not presets[preset_id].available:
            presets[preset_id] = parsed_preset

    return list(presets.values())


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean_xml_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned_value = value.strip()
    return cleaned_value or None


def decode_custom_playback_stream_url(location: str) -> str | None:
    playback_path = "/custom/v1/playback/"
    if playback_path not in location:
        return None

    encoded_stream_url = location.split(playback_path, 1)[1].split("?", 1)[0]
    try:
        return base64.b64decode(
            unquote(encoded_stream_url),
            validate=True,
        ).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


def build_library_stream_url(
    public_base_url: str,
    library_path: str,
    playback_id: str | None = None,
) -> str:
    query_parameters = {"path": library_path}
    if playback_id:
        query_parameters["playback_id"] = playback_id
    query = urlencode(query_parameters)
    return urljoin(public_base_url.rstrip("/") + "/", f"api/library/file?{query}")
