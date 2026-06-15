import unittest
from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "thecakeisapi" / "webui" / "static" / "app.js"


class WebUiTransportTests(unittest.TestCase):
    def test_pause_button_becomes_resume_for_any_paused_output(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('pauseButton.textContent = isPaused ? "Resume" : "Pause";', app_js)
        self.assertIn(
            'return playbackState?.state === "paused" || playbackState?.paused === true;',
            app_js,
        )
        self.assertIn(
            "playButton.disabled = !hasTrack || isPlaying || isPaused;",
            app_js,
        )

    def test_pause_button_resumes_local_and_bose_outputs(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('sendTransportCommand("/api/player/bose/resume");', app_js)
        self.assertIn('sendTransportCommand("/api/player/local/resume");', app_js)
        self.assertIn('sendTransportCommand("/api/player/bose/pause");', app_js)
        self.assertIn('sendTransportCommand("/api/player/local/pause");', app_js)

    def test_play_button_is_available_for_stopped_bose_queue_item(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertNotIn(
            "playButton.disabled = isBose || !hasTrack || isPlaying || isPaused;",
            app_js,
        )
        self.assertIn("sendTransportCommand(transportEndpoint(\"resume\"));", app_js)


if __name__ == "__main__":
    unittest.main()
