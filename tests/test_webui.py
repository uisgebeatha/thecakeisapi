import unittest
from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "thecakeisapi" / "webui" / "static" / "app.js"
INDEX_HTML = Path(__file__).resolve().parents[1] / "thecakeisapi" / "webui" / "index.html"
STYLES_CSS = Path(__file__).resolve().parents[1] / "thecakeisapi" / "webui" / "static" / "styles.css"
PACKAGE_INIT = Path(__file__).resolve().parents[1] / "thecakeisapi" / "__init__.py"
MAIN_PY = Path(__file__).resolve().parents[1] / "thecakeisapi" / "main.py"


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

    def test_bose_is_the_default_playback_output(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")
        index_html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn('name="playback-output" value="bose" checked', index_html)
        self.assertIn('name="playback-output" value="local"', index_html)
        self.assertIn('input[name="playback-output"]', app_js)

    def test_bose_and_local_selections_use_distinct_play_requests(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('bose: "/api/player/bose/play"', app_js)
        self.assertIn('local: "/api/player/local/play"', app_js)
        self.assertIn("return PLAY_ENDPOINTS[selectedOutput()];", app_js)
        self.assertIn("fetch(`${playEndpoint()}?${params.toString()}`", app_js)

    def test_output_selection_reads_the_checked_radio(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn(
            "const selectedOption = outputOptions.find((option) => option.checked);",
            app_js,
        )
        self.assertIn(
            'return selectedOption?.value === "local" ? "local" : "bose";',
            app_js,
        )

    def test_transport_controls_target_the_active_output(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn("function transportOutput()", app_js)
        self.assertIn("? lastPlaybackState.active_output", app_js)
        self.assertIn("const output = transportOutput();", app_js)

    def test_ui_has_dedicated_version_and_active_output_indicators(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        styles_css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertIn('id="app-version" class="version-note"', index_html)
        self.assertIn('id="active-output" class="active-output"', index_html)
        self.assertIn(".version-note", styles_css)
        self.assertIn(".active-output", styles_css)

    def test_versioned_assets_prevent_old_selector_code_from_being_reused(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        main_py = MAIN_PY.read_text(encoding="utf-8")

        self.assertIn("/static/styles.css?v=__THECAKEISAPI_VERSION__", index_html)
        self.assertIn("/static/app.js?v=__THECAKEISAPI_VERSION__", index_html)
        self.assertIn("v__THECAKEISAPI_VERSION__", index_html)
        self.assertIn("index_html.replace(APP_VERSION_TOKEN, __version__)", main_py)
        self.assertIn('headers={"Cache-Control": "no-cache"}', main_py)

    def test_narrow_version_label_does_not_shrink_or_wrap(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertRegex(
            styles_css,
            r"\.version-note\s*\{[^}]*flex: 0 0 auto;"
            r"[^}]*min-width: max-content;[^}]*white-space: nowrap;",
        )

    def test_output_selection_style_does_not_require_has_support(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertIn(
            ".output-option input:checked + .output-option-label",
            styles_css,
        )
        self.assertNotIn(".output-option:has(input:checked)", styles_css)
        self.assertNotIn("pointer-events: none", styles_css)

    def test_application_version_has_one_runtime_source(self) -> None:
        package_init = PACKAGE_INIT.read_text(encoding="utf-8")
        main_py = MAIN_PY.read_text(encoding="utf-8")
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        app_js = APP_JS.read_text(encoding="utf-8")
        styles_css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertIn('__version__ = "0.4.1"', package_init)
        self.assertIn("version=__version__", main_py)
        self.assertIn('"version": __version__', main_py)
        self.assertNotIn("0.4.0", index_html)
        self.assertNotIn("0.4.0", app_js)
        self.assertNotIn("0.4.0", styles_css)

    def test_ui_includes_phone_and_desktop_layout_rules(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertIn("grid-template-columns: minmax(0, 1fr) clamp(", styles_css)
        self.assertIn("@media (max-width: 760px)", styles_css)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr));", styles_css)


if __name__ == "__main__":
    unittest.main()
