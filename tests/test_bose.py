import base64
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from fastapi import HTTPException

from thecakeisapi.bose import (
    AfterTouchClient,
    BoseNowPlayingClient,
    BoseNowPlayingStatus,
    BosePreset,
    BosePlaybackRequest,
    BosePlaybackState,
    BosePlaybackError,
    SoundTouchCliClient,
    build_library_stream_url,
    parse_now_playing,
    parse_presets,
)
from thecakeisapi.main import (
    _play_bose_track,
    _play_track,
    _playback_status,
    _observe_external_bose_playback,
    _pause_bose_playback,
    _poll_bose_playback_state,
    _resume_bose_playback,
    _select_bose_preset,
    _stop_bose_playback,
    _sync_bose_playback,
    create_app,
)
from thecakeisapi.playlist import QueueTrack
from thecakeisapi.settings import Settings


TEST_PUBLIC_BASE_URL = "http://192.168.42.190:8000"
TEST_AFTERTOUCH_BASE_URL = "http://bose-controller.local"
TEST_PLAYBACK_ID = "test-playback-id"


def test_stream_url(path: str, playback_id: str = TEST_PLAYBACK_ID) -> str:
    return build_library_stream_url(
        TEST_PUBLIC_BASE_URL,
        path,
        playback_id=playback_id,
    )


def custom_radio_status(
    stream_url: str,
    track_name: str = "Test track",
    play_status: str = "PLAY_STATE",
) -> str:
    encoded_stream_url = base64.b64encode(stream_url.encode("utf-8")).decode("ascii")
    location = (
        f"{TEST_AFTERTOUCH_BASE_URL}/custom/v1/playback/"
        f"{encoded_stream_url}?name={track_name.replace(' ', '+')}"
    )
    return (
        '<nowPlaying source="LOCAL_INTERNET_RADIO">'
        f'<ContentItem source="LOCAL_INTERNET_RADIO" type="stationurl" '
        f'location="{location}" sourceAccount="">'
        f"<itemName>{track_name}</itemName>"
        "</ContentItem>"
        f"<track>{track_name}</track>"
        f"<playStatus>{play_status}</playStatus>"
        "</nowPlaying>"
    )


def app_owned_bose_state(**overrides) -> BosePlaybackState:
    values = {
        "track_path": "first.mp3",
        "track_name": "first.mp3",
        "state": "playing",
        "ownership_stream_url": test_stream_url("first.mp3"),
        "ownership_confirmed": True,
    }
    values.update(overrides)
    return BosePlaybackState(**values)


def route_endpoint(app, path: str, method: str):
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == path and method in route.methods
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

    def test_library_stream_url_can_include_playback_ownership_marker(self) -> None:
        self.assertEqual(
            test_stream_url("Album One/song.mp3"),
            "http://192.168.42.190:8000/api/library/file"
            "?path=Album+One%2Fsong.mp3&playback_id=test-playback-id",
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


class BosePresetTests(unittest.TestCase):
    def test_parses_six_populated_presets_in_numeric_order(self) -> None:
        raw_presets = "<presets>" + "".join(
            (
                f'<preset id="{preset_id}">'
                f'<ContentItem source="SOURCE_{preset_id}" type="stationurl" '
                f'location="preset:{preset_id}">'
                f"<itemName>Preset {preset_id}</itemName>"
                "</ContentItem></preset>"
            )
            for preset_id in reversed(range(1, 7))
        ) + "</presets>"

        presets = parse_presets(raw_presets)

        self.assertEqual([preset.id for preset in presets], [1, 2, 3, 4, 5, 6])
        self.assertTrue(all(preset.available for preset in presets))
        self.assertEqual(presets[1].display_name, "Preset 2")
        self.assertEqual(presets[1].source, "SOURCE_2")
        self.assertEqual(presets[1].content_type, "stationurl")
        self.assertEqual(presets[1].location, "preset:2")

    def test_empty_missing_and_malformed_entries_are_unavailable(self) -> None:
        presets = parse_presets(
            "<presets>"
            '<preset id="invalid"><ContentItem source="BAD" /></preset>'
            '<preset id="2"><ContentItem source="INVALID_SOURCE" '
            'type="INVALID_CONTENT_TYPE" location="" /></preset>'
            '<preset id="3"><ContentItem source="TUNEIN">'
            "<itemName>  Radio Three  </itemName>"
            "</ContentItem></preset>"
            '<preset id="4"><unexpected /></preset>'
            '<preset id="9"><ContentItem source="OUT_OF_RANGE" /></preset>'
            "</presets>",
        )

        self.assertEqual([preset.id for preset in presets], [1, 2, 3, 4, 5, 6])
        self.assertFalse(presets[0].available)
        self.assertFalse(presets[1].available)
        self.assertIsNone(presets[1].source)
        self.assertTrue(presets[2].available)
        self.assertEqual(presets[2].display_name, "Radio Three")
        self.assertFalse(presets[3].available)
        self.assertFalse(presets[4].available)
        self.assertFalse(presets[5].available)

    def test_invalid_presets_xml_uses_playback_error(self) -> None:
        with self.assertRaisesRegex(BosePlaybackError, "invalid XML"):
            parse_presets("<presets><preset></presets>")

    @patch("thecakeisapi.bose.urlopen")
    def test_fetch_presets_reads_bose_presets_endpoint(self, urlopen_mock) -> None:
        urlopen_mock.return_value.__enter__.return_value.read.return_value = (
            b'<presets><preset id="1"><ContentItem source="TUNEIN">'
            b"<itemName>Preset One</itemName></ContentItem></preset></presets>"
        )

        presets = BoseNowPlayingClient("192.168.42.101").fetch_presets()

        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "http://192.168.42.101:8090/presets")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(presets[0].display_name, "Preset One")

    @patch("thecakeisapi.bose.urlopen")
    def test_selects_each_physical_preset_with_press_and_release(self, urlopen_mock) -> None:
        urlopen_mock.return_value.__enter__.return_value.read.return_value = b"<status>OK</status>"
        client = BoseNowPlayingClient("192.168.42.101")

        for preset_id in range(1, 7):
            client.select_preset(preset_id)

        requests = [call.args[0] for call in urlopen_mock.call_args_list]
        self.assertEqual(len(requests), 12)
        for preset_id in range(1, 7):
            press_request = requests[(preset_id - 1) * 2]
            release_request = requests[(preset_id - 1) * 2 + 1]
            self.assertEqual(press_request.full_url, "http://192.168.42.101:8090/key")
            self.assertEqual(press_request.get_method(), "POST")
            self.assertEqual(
                press_request.data.decode("utf-8"),
                f'<key state="press" sender="Gabbo">PRESET_{preset_id}</key>',
            )
            self.assertEqual(
                release_request.data.decode("utf-8"),
                f'<key state="release" sender="Gabbo">PRESET_{preset_id}</key>',
            )

    def test_invalid_preset_id_is_rejected_before_transport(self) -> None:
        client = BoseNowPlayingClient("192.168.42.101")

        for preset_id in (0, 7):
            with self.assertRaisesRegex(BosePlaybackError, "between 1 and 6"):
                client.select_preset(preset_id)

    @patch("thecakeisapi.bose.urlopen")
    def test_control_actions_send_one_press_and_release_pair(self, urlopen_mock) -> None:
        urlopen_mock.return_value.__enter__.return_value.read.return_value = (
            b"<status>OK</status>"
        )
        client = BoseNowPlayingClient("192.168.42.101")

        for action in ("volume-up", "volume-down", "power"):
            client.send_control_action(action)

        requests = [call.args[0] for call in urlopen_mock.call_args_list]
        self.assertEqual(len(requests), 6)
        for index, key_name in enumerate(("VOLUME_UP", "VOLUME_DOWN", "POWER")):
            press_request = requests[index * 2]
            release_request = requests[index * 2 + 1]
            self.assertEqual(press_request.full_url, "http://192.168.42.101:8090/key")
            self.assertEqual(press_request.get_method(), "POST")
            self.assertEqual(
                press_request.data.decode("utf-8"),
                f'<key state="press" sender="Gabbo">{key_name}</key>',
            )
            self.assertEqual(
                release_request.data.decode("utf-8"),
                f'<key state="release" sender="Gabbo">{key_name}</key>',
            )

    @patch("thecakeisapi.bose.urlopen")
    def test_invalid_control_action_is_rejected_before_transport(self, urlopen_mock) -> None:
        with self.assertRaisesRegex(BosePlaybackError, "Unsupported Bose control action"):
            BoseNowPlayingClient("192.168.42.101").send_control_action("mute")

        urlopen_mock.assert_not_called()


class BoseNowPlayingTests(unittest.TestCase):
    def test_external_display_name_prefers_track_then_station_then_item(self) -> None:
        status = parse_now_playing(
            '<nowPlaying source="TUNEIN">'
            '<ContentItem source="TUNEIN"><itemName>Preset item</itemName></ContentItem>'
            "<track>Current track</track><stationName>BBC Radio 2</stationName>"
            "</nowPlaying>",
        )
        self.assertEqual(status.display_name, "Current track")

        station_status = parse_now_playing(
            '<nowPlaying source="TUNEIN">'
            '<ContentItem source="TUNEIN"><itemName>Preset item</itemName></ContentItem>'
            "<stationName>BBC Radio 2</stationName>"
            "</nowPlaying>",
        )
        self.assertEqual(station_status.display_name, "BBC Radio 2")

        item_status = parse_now_playing(
            '<nowPlaying source="LOCAL_INTERNET_RADIO">'
            '<ContentItem source="LOCAL_INTERNET_RADIO">'
            "<itemName>old-song.mp3</itemName></ContentItem>"
            "</nowPlaying>",
        )
        self.assertEqual(item_status.display_name, "old-song.mp3")

    def test_external_display_name_uses_sensible_source_fallback(self) -> None:
        status = parse_now_playing('<nowPlaying source="AUX"></nowPlaying>')

        self.assertEqual(status.display_name, "AUX")

    def test_now_playing_retains_content_metadata_and_matches_tagged_stream(self) -> None:
        stream_url = test_stream_url("first.mp3")

        status = parse_now_playing(custom_radio_status(stream_url, "First"))

        self.assertEqual(status.source, "LOCAL_INTERNET_RADIO")
        self.assertEqual(status.source_account, "")
        self.assertEqual(status.content_type, "stationurl")
        self.assertIn("/custom/v1/playback/", status.content_location)
        self.assertTrue(status.matches_stream_url(stream_url))
        self.assertFalse(status.matches_stream_url(test_stream_url("second.mp3")))

    def test_expected_stream_marker_is_required_for_ownership_confirmation(self) -> None:
        app_stream_url = test_stream_url("first.mp3")
        preset_stream_url = build_library_stream_url(
            TEST_PUBLIC_BASE_URL,
            "first.mp3",
        )
        client = FakeNowPlayingClient(
            [
                custom_radio_status(preset_stream_url, "Old preset"),
                custom_radio_status(app_stream_url, "First"),
            ],
        )

        status = client.wait_for_custom_radio(
            timeout_seconds=1,
            poll_interval_seconds=0.001,
            expected_stream_url=app_stream_url,
        )

        self.assertIsNotNone(status)
        self.assertEqual(status.track_name, "First")
        self.assertEqual(client.fetch_count, 2)

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

    def test_next_custom_radio_track_requires_a_source_transition(self) -> None:
        previous_status = parse_now_playing(
            '<nowPlaying source="LOCAL_INTERNET_RADIO"><track>First</track></nowPlaying>',
        )
        client = FakeNowPlayingClient(
            [
                '<nowPlaying source="LOCAL_INTERNET_RADIO"><track>First</track></nowPlaying>',
                '<nowPlaying source="INVALID_SOURCE"></nowPlaying>',
                '<nowPlaying source="LOCAL_INTERNET_RADIO"><track>Second</track></nowPlaying>',
            ],
        )

        status = client.wait_for_custom_radio(
            timeout_seconds=1,
            poll_interval_seconds=0.001,
            previous_status=previous_status,
        )

        self.assertIsNotNone(status)
        self.assertIn("Second", status.raw_text)
        self.assertEqual(client.fetch_count, 3)

    def test_unchanged_custom_radio_status_does_not_confirm_next_track(self) -> None:
        raw_status = (
            '<nowPlaying source="LOCAL_INTERNET_RADIO"><track>First</track></nowPlaying>'
        )
        previous_status = parse_now_playing(raw_status)
        client = FakeNowPlayingClient([raw_status])

        status = client.wait_for_custom_radio(
            timeout_seconds=0,
            poll_interval_seconds=0.001,
            previous_status=previous_status,
        )

        self.assertIsNone(status)

    def test_changed_track_metadata_confirms_next_custom_radio_track(self) -> None:
        previous_status = parse_now_playing(
            '<nowPlaying source="LOCAL_INTERNET_RADIO"><track>First</track></nowPlaying>',
        )
        client = FakeNowPlayingClient(
            [
                '<nowPlaying source="LOCAL_INTERNET_RADIO">'
                '<track>Second</track></nowPlaying>',
            ],
        )

        status = client.wait_for_custom_radio(
            timeout_seconds=0,
            poll_interval_seconds=0.001,
            previous_status=previous_status,
        )

        self.assertIsNotNone(status)
        self.assertEqual(status.track_name, "Second")

    def test_invalid_source_is_recognized_as_a_transition(self) -> None:
        status = parse_now_playing(
            '<nowPlaying source="INVALID_SOURCE"></nowPlaying>',
        )

        self.assertTrue(status.appears_to_be_invalid_source)
        self.assertFalse(status.appears_to_be_custom_radio)

    def test_now_playing_parses_stopped_play_status(self) -> None:
        status = parse_now_playing(
            '<nowPlaying source="LOCAL_INTERNET_RADIO">'
            '<playStatus>STOP_STATE</playStatus></nowPlaying>',
        )

        self.assertEqual(status.play_status, "STOP_STATE")
        self.assertTrue(status.appears_to_be_stopped)
        self.assertFalse(status.appears_to_be_standby)

    @patch("thecakeisapi.bose.urlopen", side_effect=TimeoutError("timed out"))
    def test_now_playing_timeout_uses_playback_error(self, _urlopen_mock) -> None:
        client = BoseNowPlayingClient("192.168.42.101")

        with self.assertRaisesRegex(BosePlaybackError, "now_playing request failed"):
            client.fetch_status()


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
            "Bose resume restarts playback; timer reset",
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

    def test_default_bose_state_poll_interval_is_five_seconds(self) -> None:
        self.assertEqual(Settings().bose_state_poll_interval_seconds, 5.0)

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
            app.state.bose_playback_state = app_owned_bose_state(
                confirmed_start_timestamp=time.time() - 2,
                duration_seconds=10.0,
            )

            _play_track(app, QueueTrack(path="first.mp3", name="first.mp3"))

            self.assertTrue(app.state.bose_client.stopped)
            self.assertEqual(local_player.played_paths, ["first.mp3"])


class BosePresetApiTests(unittest.TestCase):
    def test_preset_endpoint_returns_ordered_public_slots_without_location(self) -> None:
        with temp_music_app() as app:
            app.state.bose_now_playing_client = FakePresetClient(
                presets=parse_presets(
                    "<presets>"
                    '<preset id="2"><ContentItem source="TUNEIN" '
                    'location="station:private"><itemName>Second</itemName>'
                    "</ContentItem></preset>"
                    '<preset id="1"><ContentItem source="LOCAL_INTERNET_RADIO" '
                    'location="file:private"><itemName>First</itemName>'
                    "</ContentItem></preset>"
                    "</presets>",
                ),
            )

            response = route_endpoint(
                app,
                "/api/player/bose/presets",
                "GET",
            )()

            self.assertEqual(
                [preset["id"] for preset in response["presets"]],
                [1, 2, 3, 4, 5, 6],
            )
            self.assertEqual(response["presets"][0]["display_name"], "First")
            self.assertNotIn("location", response["presets"][0])
            self.assertFalse(response["presets"][5]["available"])

    def test_preset_endpoint_reports_unreachable_speaker_cleanly(self) -> None:
        with temp_music_app() as app:
            app.state.bose_now_playing_client = FakePresetClient(
                fetch_error=BosePlaybackError("Bose presets request failed: offline"),
            )

            with self.assertRaises(HTTPException) as raised:
                route_endpoint(app, "/api/player/bose/presets", "GET")()

            self.assertEqual(raised.exception.status_code, 503)
            self.assertIn("offline", raised.exception.detail)

    def test_invalid_preset_ids_are_rejected_by_activation_endpoint(self) -> None:
        with temp_music_app() as app:
            endpoint = route_endpoint(
                app,
                "/api/player/bose/presets/{preset_id}/activate",
                "POST",
            )

            for preset_id in (0, 7):
                with self.assertRaises(HTTPException) as raised:
                    endpoint(preset_id)
                self.assertEqual(raised.exception.status_code, 400)

    def test_preset_selection_clears_queue_and_app_ownership(self) -> None:
        with temp_music_app() as app:
            app.state.local_player = FakeLocalPlayer()
            app.state.playback_queue.set_tracks(
                [
                    QueueTrack(path="first.mp3", name="first.mp3"),
                    QueueTrack(path="second.mp3", name="second.mp3"),
                ],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                confirmed_start_timestamp=time.time() - 2,
                duration_seconds=10.0,
            )
            preset_client = FakePresetClient()
            app.state.bose_now_playing_client = preset_client

            status = route_endpoint(
                app,
                "/api/player/bose/presets/{preset_id}/activate",
                "POST",
            )(3)

            self.assertEqual(preset_client.selected_ids, [3])
            self.assertEqual(app.state.local_player.stop_count, 1)
            self.assertEqual(status["queue"], [])
            self.assertIsNone(status["now_playing"])
            self.assertEqual(status["active_output"], "bose")
            self.assertTrue(status["bose"]["external_playback_active"])
            self.assertFalse(app.state.bose_playback_state.has_app_ownership_context)
            self.assertIsNone(app.state.bose_playback_state.track_path)

    def test_selected_preset_remains_external_after_now_playing_observation(self) -> None:
        with temp_music_app() as app:
            preset_client = FakePresetClient(
                status_xml=(
                    '<nowPlaying source="TUNEIN">'
                    '<ContentItem source="TUNEIN"><itemName>Preset radio</itemName>'
                    "</ContentItem><stationName>Station title</stationName>"
                    "<playStatus>PLAY_STATE</playStatus></nowPlaying>"
                ),
            )
            app.state.bose_now_playing_client = preset_client

            _select_bose_preset(app, 2)
            _observe_external_bose_playback(app, now_monotonic=10.0)

            state = app.state.bose_playback_state
            self.assertTrue(state.external_playback_active)
            self.assertFalse(state.has_app_ownership_context)
            self.assertEqual(state.external_display_name, "Station title")
            self.assertEqual(state.external_source, "TUNEIN")

    def test_app_track_after_preset_establishes_fresh_ownership(self) -> None:
        with temp_music_app() as app:
            app.state.bose_playback_state = app_owned_bose_state(
                ownership_stream_url=test_stream_url("first.mp3", "old-playback-id"),
            )
            app.state.bose_now_playing_client = FakePresetClient()

            _select_bose_preset(app, 4)
            self.assertFalse(app.state.bose_playback_state.has_app_ownership_context)

            app.state.bose_playback_id_factory = lambda: "fresh-playback-id"
            app.state.bose_now_playing_client = FakeOwnedNowPlayingClient(app)
            _play_bose_track(app, QueueTrack(path="second.mp3", name="second.mp3"))

            state = app.state.bose_playback_state
            self.assertTrue(state.ownership_confirmed)
            self.assertFalse(state.external_playback_active)
            self.assertIn("playback_id=fresh-playback-id", state.ownership_stream_url)
            self.assertNotIn("old-playback-id", state.ownership_stream_url)

    def test_failed_preset_selection_clears_stale_ownership_safely(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [QueueTrack(path="first.mp3", name="first.mp3")],
                "first.mp3",
            )
            app.state.bose_playback_state = app_owned_bose_state()
            app.state.bose_now_playing_client = FakePresetClient(
                select_error=BosePlaybackError("speaker unavailable"),
            )

            with self.assertRaisesRegex(BosePlaybackError, "speaker unavailable"):
                _select_bose_preset(app, 1)

            self.assertFalse(app.state.bose_playback_state.has_app_ownership_context)
            self.assertFalse(app.state.bose_playback_state.external_playback_active)
            self.assertEqual(app.state.playback_queue.as_dict()["tracks"], [])
            self.assertEqual(app.state.bose_playback_state.state, "stopped")


class BoseControlApiTests(unittest.TestCase):
    def test_allowlisted_controls_preserve_queue_and_playback_ownership(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [
                    QueueTrack(path="first.mp3", name="first.mp3"),
                    QueueTrack(path="second.mp3", name="second.mp3"),
                ],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state()
            control_client = FakePresetClient()
            app.state.bose_now_playing_client = control_client
            endpoint = route_endpoint(
                app,
                "/api/player/bose/control/{action}",
                "POST",
            )

            for action in ("volume-up", "volume-down", "power"):
                status = endpoint(action)

            self.assertEqual(
                control_client.control_actions,
                ["volume-up", "volume-down", "power"],
            )
            self.assertEqual(
                [track["path"] for track in status["queue"]],
                ["first.mp3", "second.mp3"],
            )
            self.assertEqual(status["now_playing"]["path"], "first.mp3")
            self.assertEqual(status["active_output"], "bose")
            self.assertTrue(app.state.bose_playback_state.has_app_ownership_context)
            self.assertFalse(app.state.bose_playback_state.external_playback_active)

    def test_power_control_does_not_create_playback_ownership(self) -> None:
        with temp_music_app() as app:
            control_client = FakePresetClient()
            app.state.bose_now_playing_client = control_client

            status = route_endpoint(
                app,
                "/api/player/bose/control/{action}",
                "POST",
            )("power")

            self.assertEqual(control_client.control_actions, ["power"])
            self.assertFalse(app.state.bose_playback_state.has_app_ownership_context)
            self.assertIsNone(status["now_playing"])
            self.assertEqual(status["queue"], [])

    def test_invalid_control_action_is_rejected_by_api(self) -> None:
        with temp_music_app() as app:
            control_client = FakePresetClient()
            app.state.bose_now_playing_client = control_client
            endpoint = route_endpoint(
                app,
                "/api/player/bose/control/{action}",
                "POST",
            )

            with self.assertRaises(HTTPException) as raised:
                endpoint("mute")

            self.assertEqual(raised.exception.status_code, 400)
            self.assertEqual(control_client.control_actions, [])


class BosePlaybackOwnershipTests(unittest.TestCase):
    def test_app_started_custom_radio_is_recognized_as_owned(self) -> None:
        with temp_music_app() as app:
            _play_bose_track(app, QueueTrack(path="first.mp3", name="first.mp3"))

            state = app.state.bose_playback_state
            self.assertTrue(state.ownership_confirmed)
            self.assertTrue(state.has_app_ownership_context)
            self.assertEqual(state.state, "playing")
            self.assertIn("playback_id=test-playback-id", app.state.bose_client.played_urls[0])

    def test_old_thecakeisapi_style_physical_preset_is_external(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [QueueTrack(path="first.mp3", name="first.mp3")],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state()
            old_preset_stream_url = build_library_stream_url(
                TEST_PUBLIC_BASE_URL,
                "first.mp3",
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [custom_radio_status(old_preset_stream_url, "Old preset")],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)

            state = app.state.bose_playback_state
            self.assertEqual(state.state, "stopped")
            self.assertTrue(state.external_playback_active)
            self.assertFalse(state.has_app_ownership_context)
            self.assertEqual(
                app.state.playback_message,
                "Bose playback is active externally on LOCAL_INTERNET_RADIO",
            )
            self.assertIsNone(_playback_status(app)["now_playing"])
            self.assertEqual(len(_playback_status(app)["queue"]), 1)

    def test_normal_external_radio_preset_is_not_app_owned(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state()
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    '<nowPlaying source="TUNEIN">'
                    '<ContentItem source="TUNEIN" location="station:123" '
                    'sourceAccount="account"><itemName>Radio</itemName></ContentItem>'
                    "</nowPlaying>",
                ],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)

            self.assertTrue(app.state.bose_playback_state.external_playback_active)
            self.assertFalse(app.state.bose_playback_state.has_app_ownership_context)
            self.assertIn("TUNEIN", app.state.playback_message)

    def test_aux_is_not_app_owned(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state()
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                ['<nowPlaying source="AUX"></nowPlaying>'],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)

            self.assertTrue(app.state.bose_playback_state.external_playback_active)
            self.assertFalse(app.state.bose_playback_state.has_app_ownership_context)
            self.assertIn("AUX", app.state.playback_message)

    def test_stop_only_sends_command_for_app_owned_playback(self) -> None:
        with temp_music_app() as app:
            app.state.bose_playback_state = BosePlaybackState(
                state="stopped",
                external_playback_active=True,
            )

            self.assertFalse(_stop_bose_playback(app))
            self.assertFalse(app.state.bose_client.stopped)

            app.state.bose_playback_state = app_owned_bose_state()
            self.assertTrue(_stop_bose_playback(app))
            self.assertTrue(app.state.bose_client.stopped)

    def test_stop_rechecks_ownership_after_external_preset_takeover(self) -> None:
        with temp_music_app() as app:
            app.state.bose_playback_state = app_owned_bose_state()
            old_preset_stream_url = build_library_stream_url(
                TEST_PUBLIC_BASE_URL,
                "first.mp3",
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [custom_radio_status(old_preset_stream_url, "Old preset")],
            )

            self.assertFalse(_stop_bose_playback(app))
            self.assertFalse(app.state.bose_client.stopped)
            self.assertTrue(app.state.bose_playback_state.external_playback_active)
            self.assertFalse(app.state.bose_playback_state.has_app_ownership_context)

    def test_external_takeover_clears_then_new_app_start_reestablishes_ownership(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state()
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [custom_radio_status("https://radio.example/external", "External")],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)
            self.assertFalse(app.state.bose_playback_state.has_app_ownership_context)

            app.state.bose_now_playing_client = FakeOwnedNowPlayingClient(app)
            _play_bose_track(app, QueueTrack(path="second.mp3", name="second.mp3"))

            self.assertTrue(app.state.bose_playback_state.ownership_confirmed)
            self.assertFalse(app.state.bose_playback_state.external_playback_active)
            self.assertEqual(app.state.bose_playback_state.track_path, "second.mp3")


class ExternalBosePlaybackDisplayTests(unittest.TestCase):
    def test_first_observed_external_radio_poll_exposes_station_name(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "local"
            app.state.bose_playback_state = BosePlaybackState()
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    '<nowPlaying source="TUNEIN">'
                    '<ContentItem source="TUNEIN">'
                    "<itemName>Radio preset</itemName></ContentItem>"
                    "<stationName>BBC Radio 2</stationName>"
                    "<playStatus>PLAY_STATE</playStatus>"
                    "</nowPlaying>",
                ],
            )

            status = route_endpoint(app, "/api/player/status", "GET")(
                observe_bose=True,
            )

            self.assertTrue(status["bose"]["external_playback_active"])
            self.assertEqual(status["bose"]["external_display_name"], "BBC Radio 2")
            self.assertEqual(status["bose"]["external_source"], "TUNEIN")
            self.assertIsNone(status["now_playing"])
            self.assertEqual(app.state.bose_now_playing_client.fetch_count, 1)

    def test_external_mp3_preset_exposes_item_name_without_queue_ownership(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state()
            old_preset_stream_url = build_library_stream_url(
                TEST_PUBLIC_BASE_URL,
                "first.mp3",
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [custom_radio_status(old_preset_stream_url, "old-song.mp3")],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)
            status = _playback_status(app)

            self.assertEqual(status["bose"]["external_display_name"], "old-song.mp3")
            self.assertTrue(status["bose"]["external_playback_active"])
            self.assertIsNone(status["now_playing"])

    def test_sparse_external_source_uses_source_label(self) -> None:
        with temp_music_app() as app:
            app.state.bose_playback_state = BosePlaybackState()
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                ['<nowPlaying source="AUX"><playStatus>PLAY_STATE</playStatus></nowPlaying>'],
            )

            _observe_external_bose_playback(app, now_monotonic=10.0)
            status = _playback_status(app)

            self.assertEqual(status["bose"]["external_display_name"], "AUX")
            self.assertEqual(status["bose"]["external_source"], "AUX")

    def test_external_observation_uses_existing_poll_interval(self) -> None:
        with temp_music_app() as app:
            app.state.bose_playback_state = BosePlaybackState()
            client = FakeNowPlayingClient(
                ['<nowPlaying source="AUX"><playStatus>PLAY_STATE</playStatus></nowPlaying>'],
            )
            app.state.bose_now_playing_client = client

            _observe_external_bose_playback(app, now_monotonic=10.0)
            _observe_external_bose_playback(app, now_monotonic=14.9)
            _observe_external_bose_playback(app, now_monotonic=15.0)

            self.assertEqual(client.fetch_count, 2)

    def test_app_owned_status_still_uses_queue_now_playing(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [QueueTrack(path="first.mp3", name="first.mp3")],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state()

            status = _playback_status(app)

            self.assertFalse(status["bose"]["external_playback_active"])
            self.assertEqual(status["now_playing"]["name"], "first.mp3")


class BoseStatePollingTests(unittest.TestCase):
    def test_poll_confirms_delayed_bose_start(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                track_path="first.mp3",
                track_name="first.mp3",
                state="starting",
                ownership_confirmed=False,
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [custom_radio_status(test_stream_url("first.mp3"), "first.mp3")],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)

            self.assertEqual(app.state.bose_playback_state.state, "playing")
            self.assertIsNotNone(
                app.state.bose_playback_state.confirmed_start_timestamp,
            )
            self.assertIsNotNone(
                app.state.bose_playback_state.last_confirmed_status_timestamp,
            )
            self.assertEqual(app.state.bose_playback_state.status_poll_failures, 0)

    def test_external_bose_stop_clears_stale_playing_state(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                track_path="first.mp3",
                track_name="first.mp3",
                confirmed_start_timestamp=time.time() - 3,
                duration_seconds=30.0,
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    custom_radio_status(
                        test_stream_url("first.mp3"),
                        "first.mp3",
                        play_status="STOP_STATE",
                    ),
                ],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)

            self.assertEqual(app.state.bose_playback_state.state, "stopped")
            self.assertIsNone(
                app.state.bose_playback_state.confirmed_start_timestamp,
            )
            self.assertEqual(app.state.playback_message, "Bose playback stopped externally")
            self.assertFalse(app.state.bose_client.stopped)
            status = _playback_status(app)
            self.assertEqual(status["state"], "stopped")
            self.assertEqual(status["bose"]["status_poll_failures"], 0)

    def test_external_bose_standby_clears_stale_playing_state(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state()
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                ['<nowPlaying source="STANDBY"></nowPlaying>'],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)

            self.assertEqual(app.state.bose_playback_state.state, "stopped")
            self.assertEqual(app.state.playback_message, "Bose playback stopped externally")

    def test_external_bose_source_change_clears_stale_playing_state(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state()
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                ['<nowPlaying source="AUX"></nowPlaying>'],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)

            self.assertEqual(app.state.bose_playback_state.state, "stopped")
            self.assertIn("AUX", app.state.playback_message)

    def test_transient_invalid_source_does_not_clear_active_playback(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.playback_message = "Playing on Bose: first.mp3"
            app.state.bose_playback_state = app_owned_bose_state(
                track_path="first.mp3",
                track_name="first.mp3",
                confirmed_start_timestamp=time.time() - 3,
                duration_seconds=30.0,
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    '<nowPlaying source="INVALID_SOURCE"></nowPlaying>',
                    custom_radio_status(test_stream_url("first.mp3"), "first.mp3"),
                ],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)

            self.assertEqual(app.state.bose_playback_state.state, "playing")
            self.assertEqual(app.state.bose_playback_state.status_poll_failures, 1)
            self.assertEqual(app.state.playback_message, "Playing on Bose: first.mp3")

            _poll_bose_playback_state(app, now_monotonic=15.0)

            self.assertEqual(app.state.bose_playback_state.state, "playing")
            self.assertEqual(app.state.bose_playback_state.status_poll_failures, 0)

    def test_bose_pause_is_not_mistaken_for_external_stop(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                state="paused",
                paused_elapsed_seconds=3.0,
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    custom_radio_status(
                        test_stream_url("first.mp3"),
                        "first.mp3",
                        play_status="STOP_STATE",
                    ),
                ],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)

            self.assertEqual(app.state.bose_playback_state.state, "paused")
            self.assertEqual(app.state.bose_playback_state.paused_elapsed_seconds, 3.0)

    def test_natural_bose_stop_still_uses_existing_auto_advance(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [
                    QueueTrack(path="first.mp3", name="first.mp3"),
                    QueueTrack(path="second.mp3", name="second.mp3"),
                ],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                confirmed_start_timestamp=time.time() - 3,
                duration_seconds=1.0,
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    custom_radio_status(
                        test_stream_url("first.mp3"),
                        "first.mp3",
                        play_status="STOP_STATE",
                    ),
                ],
            )

            _sync_bose_playback(app)

            self.assertEqual(app.state.playback_queue.current().path, "second.mp3")
            self.assertEqual(app.state.bose_client.played_names, ["second.mp3"])

    def test_invalid_source_at_auto_advance_boundary_starts_next_track(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [
                    QueueTrack(path="first.mp3", name="first.mp3"),
                    QueueTrack(path="second.mp3", name="second.mp3"),
                ],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                track_path="first.mp3",
                track_name="first.mp3",
                confirmed_start_timestamp=time.time() - 3,
                duration_seconds=1.0,
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    '<nowPlaying source="INVALID_SOURCE"></nowPlaying>',
                    '<nowPlaying source="INVALID_SOURCE"></nowPlaying>',
                    custom_radio_status(test_stream_url("second.mp3"), "Second"),
                ],
            )

            _sync_bose_playback(app)

            self.assertEqual(app.state.playback_queue.current().path, "second.mp3")
            self.assertEqual(app.state.bose_client.played_names, ["second.mp3"])
            self.assertEqual(app.state.bose_playback_state.state, "playing")
            self.assertEqual(app.state.bose_playback_state.status_poll_failures, 0)

    def test_missing_source_at_auto_advance_boundary_starts_next_track(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [
                    QueueTrack(path="first.mp3", name="first.mp3"),
                    QueueTrack(path="second.mp3", name="second.mp3"),
                ],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                track_path="first.mp3",
                track_name="first.mp3",
                confirmed_start_timestamp=time.time() - 3,
                duration_seconds=1.0,
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    "<nowPlaying></nowPlaying>",
                    "<nowPlaying></nowPlaying>",
                    custom_radio_status(test_stream_url("second.mp3"), "Second"),
                ],
            )

            _sync_bose_playback(app)

            self.assertEqual(app.state.playback_queue.current().path, "second.mp3")
            self.assertEqual(app.state.bose_client.played_names, ["second.mp3"])
            self.assertEqual(app.state.bose_playback_state.state, "playing")

    def test_expired_invalid_source_transition_clears_playback_state(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    '<nowPlaying source="LOCAL_INTERNET_RADIO">'
                    '<track>First</track></nowPlaying>',
                    '<nowPlaying source="INVALID_SOURCE"></nowPlaying>',
                ],
            )

            _play_bose_track(
                app,
                QueueTrack(path="second.mp3", name="second.mp3"),
            )

            self.assertEqual(app.state.bose_playback_state.state, "starting")
            self.assertIn("confirmation timed out", app.state.bose_playback_state.warning)

            _poll_bose_playback_state(app, now_monotonic=10.0)
            _poll_bose_playback_state(app, now_monotonic=15.0)
            _poll_bose_playback_state(app, now_monotonic=20.0)

            self.assertEqual(app.state.bose_playback_state.state, "stopped")
            self.assertEqual(app.state.bose_playback_state.status_poll_failures, 3)
            self.assertIn("transition did not settle", app.state.playback_message)

    def test_temporary_bose_query_failure_does_not_force_stop(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.playback_message = "Playing on Bose: first.mp3"
            app.state.bose_playback_state = app_owned_bose_state()
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    BosePlaybackError("temporary timeout"),
                    custom_radio_status(test_stream_url("first.mp3"), "first.mp3"),
                ],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)

            self.assertEqual(app.state.bose_playback_state.state, "playing")
            self.assertEqual(app.state.bose_playback_state.status_poll_failures, 1)
            self.assertEqual(app.state.playback_message, "Playing on Bose: first.mp3")

            _poll_bose_playback_state(app, now_monotonic=15.0)

            self.assertEqual(app.state.bose_playback_state.state, "playing")
            self.assertEqual(app.state.bose_playback_state.status_poll_failures, 0)

    def test_repeated_bose_query_failures_mark_speaker_unavailable(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_playback_state = BosePlaybackState(
                state="playing",
                confirmed_start_timestamp=time.time() - 3,
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    BosePlaybackError("offline"),
                    BosePlaybackError("offline"),
                    BosePlaybackError("offline"),
                ],
            )

            _poll_bose_playback_state(app, now_monotonic=10.0)
            _poll_bose_playback_state(app, now_monotonic=15.0)
            self.assertEqual(app.state.bose_playback_state.state, "playing")

            _poll_bose_playback_state(app, now_monotonic=20.0)

            self.assertEqual(app.state.bose_playback_state.state, "stopped")
            self.assertEqual(app.state.bose_playback_state.status_poll_failures, 3)
            self.assertIn("unavailable", app.state.playback_message)
            self.assertFalse(app.state.bose_client.stopped)

            _poll_bose_playback_state(app, now_monotonic=25.0)
            self.assertEqual(app.state.bose_now_playing_client.fetch_count, 3)

    def test_bose_polling_is_rate_limited(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state()
            client = FakeNowPlayingClient(
                [custom_radio_status(test_stream_url("first.mp3"), "first.mp3")],
            )
            app.state.bose_now_playing_client = client

            _poll_bose_playback_state(app, now_monotonic=10.0)
            _poll_bose_playback_state(app, now_monotonic=14.9)
            _poll_bose_playback_state(app, now_monotonic=15.0)

            self.assertEqual(client.fetch_count, 2)

    def test_bose_polling_does_not_run_for_local_output(self) -> None:
        with temp_music_app() as app:
            app.state.active_output = "local"
            app.state.bose_playback_state = BosePlaybackState(state="playing")
            client = FakeNowPlayingClient(
                ['<nowPlaying source="LOCAL_INTERNET_RADIO"></nowPlaying>'],
            )
            app.state.bose_now_playing_client = client

            _poll_bose_playback_state(app, now_monotonic=10.0)

            self.assertEqual(client.fetch_count, 0)

    def test_poll_failure_suspends_bose_auto_advance(self) -> None:
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
                state="playing",
                confirmed_start_timestamp=time.time() - 10,
                duration_seconds=1.0,
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [BosePlaybackError("temporary timeout")],
            )

            _sync_bose_playback(app)

            self.assertEqual(app.state.playback_queue.current().path, "first.mp3")
            self.assertEqual(app.state.bose_client.played_names, [])
            self.assertEqual(app.state.bose_playback_state.status_poll_failures, 1)


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
            app.state.bose_playback_state = app_owned_bose_state(
                track_path="first.mp3",
                track_name="first.mp3",
                confirmed_start_timestamp=time.time() - 4,
                duration_seconds=1.0,
            )

            _sync_bose_playback(app)

            self.assertEqual(app.state.playback_queue.current().path, "second.mp3")
            self.assertEqual(app.state.bose_client.played_names, ["second.mp3"])

    @patch("thecakeisapi.main.audio_duration_seconds", return_value=1.0)
    def test_bose_queue_advances_through_more_than_two_tracks(self, _duration_mock) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [
                    QueueTrack(path="first.mp3", name="first.mp3"),
                    QueueTrack(path="second.mp3", name="second.mp3"),
                    QueueTrack(path="third.mp3", name="third.mp3"),
                ],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                track_path="first.mp3",
                track_name="first.mp3",
                confirmed_start_timestamp=time.time() - 4,
                duration_seconds=1.0,
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    custom_radio_status(test_stream_url("first.mp3"), "First"),
                    custom_radio_status(test_stream_url("first.mp3"), "First"),
                    '<nowPlaying source="INVALID_SOURCE"></nowPlaying>',
                    custom_radio_status(test_stream_url("second.mp3"), "Second"),
                ],
            )

            _sync_bose_playback(app)
            self.assertEqual(app.state.playback_queue.current().path, "second.mp3")

            app.state.bose_playback_state.confirmed_start_timestamp = time.time() - 4
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    custom_radio_status(test_stream_url("second.mp3"), "Second"),
                    custom_radio_status(test_stream_url("second.mp3"), "Second"),
                    '<nowPlaying source="INVALID_SOURCE"></nowPlaying>',
                    custom_radio_status(test_stream_url("third.mp3"), "Third"),
                ],
            )

            _sync_bose_playback(app)

            self.assertEqual(app.state.playback_queue.current().path, "third.mp3")
            self.assertEqual(app.state.bose_client.played_names, ["second.mp3", "third.mp3"])

    def test_unexpired_bad_duration_does_not_restart_current_track(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [
                    QueueTrack(path="first.mp3", name="first.mp3"),
                    QueueTrack(path="second.mp3", name="second.mp3"),
                ],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                track_path="first.mp3",
                track_name="first.mp3",
                confirmed_start_timestamp=time.time() - 30,
                duration_seconds=3600.0,
            )

            _sync_bose_playback(app)
            _sync_bose_playback(app)

            self.assertEqual(app.state.playback_queue.current().path, "first.mp3")
            self.assertEqual(app.state.bose_client.played_names, [])

    @patch("thecakeisapi.main.audio_duration_seconds", return_value=1.0)
    def test_manual_next_and_previous_keep_bose_track_selection(self, _duration_mock) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [
                    QueueTrack(path="first.mp3", name="first.mp3"),
                    QueueTrack(path="second.mp3", name="second.mp3"),
                ],
                "first.mp3",
            )
            app.state.active_output = "bose"

            next_track = app.state.playback_queue.next()
            _play_bose_track(app, next_track)
            previous_track = app.state.playback_queue.previous()
            _play_bose_track(app, previous_track)

            self.assertEqual(app.state.playback_queue.current().path, "first.mp3")
            self.assertEqual(app.state.bose_client.played_names, ["second.mp3", "first.mp3"])

    def test_bose_repeat_replays_current_track(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [QueueTrack(path="first.mp3", name="first.mp3")],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.repeat_track = True
            app.state.bose_playback_state = app_owned_bose_state(
                track_path="first.mp3",
                track_name="first.mp3",
                confirmed_start_timestamp=time.time() - 4,
                duration_seconds=1.0,
            )

            _sync_bose_playback(app)

            self.assertEqual(app.state.playback_queue.current().path, "first.mp3")
            self.assertEqual(app.state.bose_client.played_names, ["first.mp3"])

    def test_bose_stop_cancels_timer_state(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [QueueTrack(path="first.mp3", name="first.mp3")],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                confirmed_start_timestamp=time.time() - 4,
                duration_seconds=1.0,
            )

            _stop_bose_playback(app)

            self.assertTrue(app.state.bose_client.stopped)
            self.assertEqual(app.state.bose_playback_state.state, "stopped")
            self.assertIsNone(app.state.bose_playback_state.confirmed_start_timestamp)
            status = _playback_status(app)
            self.assertEqual(status["state"], "stopped")
            self.assertEqual(len(status["queue"]), 1)
            self.assertEqual(status["now_playing"]["path"], "first.mp3")

    def test_bose_pause_and_resume_update_timer_state(self) -> None:
        with temp_music_app() as app:
            app.state.bose_playback_state = app_owned_bose_state(
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
                "Bose resume restarts playback; timer reset",
            )

    def test_bose_resume_after_refresh_equivalent_pause_resets_stale_elapsed_time(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [QueueTrack(path="first.mp3", name="first.mp3")],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                track_path="first.mp3",
                track_name="first.mp3",
                state="paused",
                confirmed_start_timestamp=time.time() - 90,
                paused_elapsed_seconds=45.0,
                duration_seconds=120.0,
            )

            _resume_bose_playback(app)

            status = _playback_status(app)
            self.assertEqual(status["state"], "playing")
            self.assertLess(status["elapsed_seconds"], 0.2)
            self.assertIsNone(status["bose"]["paused_elapsed_seconds"])
            self.assertEqual(
                status["bose"]["warning"],
                "Bose resume restarts playback; timer reset",
            )

    def test_bose_playback_can_start_again_after_stop(self) -> None:
        with temp_music_app() as app:
            app.state.playback_queue.set_tracks(
                [QueueTrack(path="first.mp3", name="first.mp3")],
                "first.mp3",
            )
            app.state.active_output = "bose"
            app.state.bose_playback_state = app_owned_bose_state(
                confirmed_start_timestamp=time.time() - 4,
                duration_seconds=1.0,
            )
            app.state.bose_now_playing_client = FakeNowPlayingClient(
                [
                    custom_radio_status(test_stream_url("first.mp3"), "first.mp3"),
                    '<nowPlaying source="STANDBY"></nowPlaying>',
                    custom_radio_status(test_stream_url("first.mp3"), "first.mp3"),
                ],
            )

            _stop_bose_playback(app)
            _play_bose_track(app, QueueTrack(path="first.mp3", name="first.mp3"))

            self.assertTrue(app.state.bose_client.stopped)
            self.assertEqual(app.state.bose_client.played_names, ["first.mp3"])
            self.assertEqual(app.state.bose_playback_state.state, "playing")


class FakeNowPlayingClient(BoseNowPlayingClient):
    def __init__(self, raw_statuses: list[str | Exception]) -> None:
        self.raw_statuses = raw_statuses
        self.fetch_count = 0

    def fetch_status(self) -> BoseNowPlayingStatus:
        self.fetch_count += 1
        if len(self.raw_statuses) > 1:
            raw_status = self.raw_statuses.pop(0)
        else:
            raw_status = self.raw_statuses[0]
        if isinstance(raw_status, Exception):
            raise raw_status
        return parse_now_playing(raw_status)


class FakeBoseClient:
    def __init__(self) -> None:
        self.played_names: list[str] = []
        self.played_urls: list[str] = []
        self.stopped = False
        self.paused = False
        self.resumed = False

    def play_stream(self, name: str, stream_url: str) -> BosePlaybackRequest:
        self.played_names.append(name)
        self.played_urls.append(stream_url)
        return BosePlaybackRequest(stream_url=stream_url, command=["fake"])

    def stop(self) -> None:
        self.stopped = True

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.resumed = True


class FakePresetClient:
    def __init__(
        self,
        presets: list[BosePreset] | None = None,
        status_xml: str = '<nowPlaying source="STANDBY"></nowPlaying>',
        fetch_error: Exception | None = None,
        select_error: Exception | None = None,
    ) -> None:
        self.presets = presets or parse_presets("<presets />")
        self.status_xml = status_xml
        self.fetch_error = fetch_error
        self.select_error = select_error
        self.selected_ids: list[int] = []
        self.control_actions: list[str] = []

    def fetch_presets(self) -> list[BosePreset]:
        if self.fetch_error:
            raise self.fetch_error
        return self.presets

    def select_preset(self, preset_id: int) -> None:
        if self.select_error:
            raise self.select_error
        self.selected_ids.append(preset_id)

    def send_control_action(self, action: str) -> None:
        self.control_actions.append(action)

    def fetch_status(self) -> BoseNowPlayingStatus:
        return parse_now_playing(self.status_xml)


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


class FakeOwnedNowPlayingClient(BoseNowPlayingClient):
    def __init__(self, app) -> None:
        self.app = app
        self.fetch_count = 0

    def fetch_status(self) -> BoseNowPlayingStatus:
        self.fetch_count += 1
        stream_url = self.app.state.bose_playback_state.ownership_stream_url
        if stream_url is None:
            return parse_now_playing('<nowPlaying source="STANDBY"></nowPlaying>')
        return parse_now_playing(
            custom_radio_status(
                stream_url,
                self.app.state.bose_playback_state.track_name or "Test track",
            ),
        )


class temp_music_app:
    def __enter__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        music_root = Path(self.temp_dir.name)
        (music_root / "first.mp3").write_bytes(b"\xff\xfb\x90d" + (b"\0" * 1000))
        (music_root / "second.mp3").write_bytes(b"\xff\xfb\x90d" + (b"\0" * 1000))
        (music_root / "third.mp3").write_bytes(b"\xff\xfb\x90d" + (b"\0" * 1000))
        self.app = create_app(
            Settings(
                music_root=music_root,
                bose_speaker_ip="192.168.42.101",
                aftertouch_base_url="http://bose-controller.local",
                public_base_url="http://192.168.42.190:8000",
                bose_start_confirm_timeout_seconds=0.01,
                bose_start_poll_interval_seconds=0.001,
                bose_auto_advance_buffer_seconds=0.5,
            ),
        )
        self.app.state.playback_monitor_stop.set()
        self.app.state.bose_client = FakeBoseClient()
        self.app.state.bose_playback_id_factory = lambda: TEST_PLAYBACK_ID
        self.app.state.bose_now_playing_client = FakeOwnedNowPlayingClient(self.app)
        return self.app

    def __exit__(self, *args):
        self.app.state.playback_monitor_stop.set()
        self.temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
