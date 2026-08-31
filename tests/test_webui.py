import unittest
from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "thecakeisapi" / "webui" / "static" / "app.js"
INDEX_HTML = Path(__file__).resolve().parents[1] / "thecakeisapi" / "webui" / "index.html"
STYLES_CSS = Path(__file__).resolve().parents[1] / "thecakeisapi" / "webui" / "static" / "styles.css"
PACKAGE_INIT = Path(__file__).resolve().parents[1] / "thecakeisapi" / "__init__.py"
MAIN_PY = Path(__file__).resolve().parents[1] / "thecakeisapi" / "main.py"


class WebUiTransportTests(unittest.TestCase):
    def test_single_play_pause_button_switches_icon_and_accessibility_state(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")
        index_html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn('id="play-button"', index_html)
        self.assertNotIn('id="pause-button"', index_html)
        self.assertNotIn("pauseButton", app_js)
        self.assertIn(
            'const playPauseLabel = isPlaying ? "Pause" : isPaused ? "Resume" : "Play";',
            app_js,
        )
        self.assertIn(
            'playButton.dataset.controlState = isPlaying ? "pause" : "play";',
            app_js,
        )
        self.assertIn('playButton.setAttribute("aria-label", playPauseLabel);', app_js)
        self.assertIn("playButton.title = playPauseLabel;", app_js)
        self.assertIn(
            'return playbackState?.state === "paused" || playbackState?.paused === true;',
            app_js,
        )

    def test_play_pause_button_uses_existing_output_specific_transport_endpoints(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn(
            'const action = lastPlaybackState?.state === "playing" ? "pause" : "resume";',
            app_js,
        )
        self.assertIn("sendTransportCommand(transportEndpoint(action));", app_js)
        self.assertIn('return `/api/player/bose/${action}`;', app_js)
        self.assertIn('return `/api/player/local/${action}`;', app_js)

    def test_play_button_is_available_for_stopped_bose_queue_item(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn(
            "playButton.disabled = externalBose || !hasTrack || isStarting;",
            app_js,
        )
        self.assertNotIn("playButton.disabled = !hasTrack || isPlaying", app_js)

    def test_external_bose_metadata_is_rendered_without_queue_ownership(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn("function isExternalBosePlayback(playbackState)", app_js)
        self.assertIn(
            'playbackState.bose.external_display_name || "Bose"',
            app_js,
        )
        self.assertIn('activeOutput.textContent = "Bose · External";', app_js)
        self.assertIn('return "External Bose playback";', app_js)

    def test_external_bose_transport_controls_remain_disabled(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn(
            'stopButton.disabled = externalBose || !hasTrack || playbackState.state === "stopped";',
            app_js,
        )
        self.assertIn("previousButton.disabled = externalBose || !hasTrack;", app_js)
        self.assertIn("nextButton.disabled = externalBose || !hasTrack;", app_js)
        self.assertIn("repeatButton.disabled = externalBose;", app_js)

    def test_selected_bose_output_requests_rate_limited_external_observation(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")
        index_html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            '? "/api/player/status?observe_bose=true"',
            app_js,
        )
        self.assertEqual(app_js.count("fetch(playbackStatusUrl())"), 2)
        self.assertIn("refreshPlaybackStatus();", app_js)
        self.assertIn(
            "/static/app.js?v=__THECAKEISAPI_VERSION__&state=quiet-bose-controls",
            index_html,
        )

    def test_mobile_now_playing_keeps_external_title_and_output_visible(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")
        mobile_rules = styles_css.split("@media (max-width: 760px)", 1)[1]
        mobile_rules = mobile_rules.split("@media (max-width: 420px)", 1)[0]

        self.assertIn(".now-playing {", mobile_rules)
        self.assertIn("grid-template-columns: auto minmax(0, 1fr);", mobile_rules)
        self.assertNotIn("display: none", mobile_rules)

    def test_transport_uses_five_inline_svg_buttons_without_visible_word_labels(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        transport_html = index_html.split(
            '<section class="transport" aria-label="Playback controls">',
            1,
        )[1].split("</section>", 1)[0]

        for button_id in (
            "previous-button",
            "play-button",
            "stop-button",
            "next-button",
            "repeat-button",
        ):
            self.assertIn(f'id="{button_id}"', transport_html)
        self.assertEqual(transport_html.count('<svg class="transport-icon'), 5)
        self.assertNotIn('id="pause-button"', transport_html)
        for visible_label in ("Play", "Pause", "Stop", "Previous", "Next", "Repeat Track"):
            self.assertNotIn(f">{visible_label}<", transport_html)

    def test_transport_order_places_play_pause_in_the_center(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        transport_html = index_html.split(
            '<section class="transport" aria-label="Playback controls">',
            1,
        )[1].split("</section>", 1)[0]

        control_positions = [
            transport_html.index(f'id="{button_id}"')
            for button_id in (
                "previous-button",
                "stop-button",
                "play-button",
                "next-button",
                "repeat-button",
            )
        ]
        self.assertEqual(control_positions, sorted(control_positions))

    def test_transport_accent_states_use_green_without_pale_or_blue_fill(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertRegex(
            styles_css,
            r"\.control-button\.primary,\s*"
            r"\.control-button\.primary:hover,\s*"
            r"\.control-button\.primary:focus-visible,\s*"
            r"\.control-button\.primary:active\s*\{[^}]*"
            r"border-color: #5dad82;[^}]*background: #20352b;[^}]*color: #8fd8b5;",
        )
        self.assertRegex(
            styles_css,
            r"\.control-button\[data-active=\"true\"\][\s\S]*?"
            r"border-color: var\(--accent\);[^}]*"
            r"background: var\(--accent-soft\);[^}]*color: var\(--accent\);",
        )
        for removed_color in ("#d7eadf", "#436aa8", "#e8eff8", "#264c87", "#84a8df", "#24344d", "#bed6fa"):
            self.assertNotIn(removed_color, styles_css)
        self.assertIn(
            "outline-color: color-mix(in srgb, var(--accent) 65%, transparent);",
            styles_css,
        )

    def test_transport_icons_keep_accessible_labels_and_repeat_state(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        app_js = APP_JS.read_text(encoding="utf-8")

        for accessible_label in ("Play", "Stop", "Previous track", "Next track"):
            self.assertIn(f'aria-label="{accessible_label}"', index_html)
            self.assertIn(f'title="{accessible_label}"', index_html)
        self.assertIn('aria-label="Repeat track off"', index_html)
        self.assertIn('aria-pressed="false"', index_html)
        self.assertIn(
            'repeatButton.dataset.active = playbackState.repeat_track ? "true" : "false";',
            app_js,
        )
        self.assertIn('repeatButton.setAttribute("aria-pressed"', app_js)
        self.assertIn('repeatButton.setAttribute("aria-label", repeatLabel);', app_js)

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

        self.assertIn('__version__ = "0.4.6"', package_init)
        self.assertIn("version=__version__", main_py)
        self.assertIn('"version": __version__', main_py)
        self.assertNotIn("0.4.0", index_html)
        self.assertNotIn("0.4.0", app_js)
        self.assertNotIn("0.4.0", styles_css)

    def test_ui_includes_phone_and_desktop_layout_rules(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertIn("grid-template-columns: minmax(0, 1fr) clamp(", styles_css)
        self.assertIn("@media (max-width: 760px)", styles_css)
        self.assertRegex(
            styles_css,
            r"\.transport\s*\{[^}]*display: flex;[^}]*flex-wrap: nowrap;",
        )

    def test_transport_and_output_selector_use_compact_stable_dimensions(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertRegex(
            styles_css,
            r"\.control-button\s*\{[^}]*width: 2\.75rem;[^}]*height: 2\.75rem;",
        )
        self.assertRegex(
            styles_css,
            r"\.control-button\.primary\s*\{[^}]*width: 3\.5rem;"
            r"[^}]*height: 3\.5rem;",
        )
        self.assertRegex(
            styles_css,
            r"\.output-option-label\s*\{[^}]*min-height: 2\.25rem;",
        )
        self.assertIn("--player-height: 13.5rem;", styles_css)
        self.assertIn("--player-height: 9.25rem;", styles_css)
        self.assertIn("overflow-x: hidden;", styles_css)

    def test_mobile_header_and_library_navigation_are_sticky(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")
        mobile_rules = styles_css.split("@media (max-width: 760px)", 1)[1]
        mobile_rules = mobile_rules.split("@media (max-width: 420px)", 1)[0]

        self.assertRegex(
            mobile_rules,
            r"\.topbar\s*\{[^}]*position: sticky;[^}]*top: 0;",
        )
        self.assertRegex(
            mobile_rules,
            r"\.browser-header\s*\{[^}]*position: sticky;[^}]*top: 3\.25rem;",
        )
        self.assertIn("position: fixed;", styles_css)

    def test_desktop_keeps_header_and_queue_while_library_scrolls(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")
        desktop_rules = styles_css.split("@media (min-width: 761px)", 1)[1]
        desktop_rules = desktop_rules.split("@media (max-width: 1040px)", 1)[0]

        self.assertRegex(
            desktop_rules,
            r"body\s*\{[^}]*overflow-y: hidden;",
        )
        self.assertRegex(
            desktop_rules,
            r"\.shell\s*\{[^}]*grid-template-rows: auto minmax\(0, 1fr\);"
            r"[^}]*height: 100dvh;[^}]*overflow: hidden;",
        )
        self.assertRegex(
            desktop_rules,
            r"\.topbar\s*\{[^}]*position: sticky;[^}]*top: 0;",
        )
        self.assertRegex(
            desktop_rules,
            r"\.browser\s*\{[^}]*overflow-y: auto;",
        )
        self.assertRegex(
            desktop_rules,
            r"\.playlist-panel\s*\{[^}]*position: sticky;[^}]*overflow: hidden;",
        )
        self.assertRegex(
            desktop_rules,
            r"\.queue-list\s*\{[^}]*overflow-y: auto;",
        )

    def test_mobile_queue_keeps_document_scroll_behavior(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")
        mobile_rules = styles_css.split("@media (max-width: 760px)", 1)[1]
        mobile_rules = mobile_rules.split("@media (max-width: 420px)", 1)[0]

        self.assertNotRegex(
            mobile_rules,
            r"\.playlist-panel\s*\{[^}]*(?:position: sticky|overflow-y: auto);",
        )
        self.assertNotRegex(
            mobile_rules,
            r"\.queue-list\s*\{[^}]*overflow-y: auto;",
        )

    def test_settings_dialog_exposes_only_supported_editable_fields(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn('id="settings-dialog"', index_html)
        for field_name in (
            "bose_speaker_ip",
            "aftertouch_base_url",
            "soundtouch_cli_command",
            "public_base_url",
            "bose_state_poll_interval_seconds",
        ):
            self.assertIn(f'name="{field_name}"', index_html)
        self.assertNotIn('name="music_root"', index_html)
        self.assertNotIn('name="bose_api_port"', index_html)

    def test_settings_dialog_separates_configuration_status_and_actions(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")

        section_positions = [
            index_html.index(f'id="{heading_id}"')
            for heading_id in (
                "configuration-heading",
                "component-status-heading",
                "settings-actions-heading",
            )
        ]
        self.assertEqual(section_positions, sorted(section_positions))
        self.assertIn(
            'id="settings-save-button" class="settings-save-button" '
            'type="submit" form="settings-form"',
            index_html,
        )
        self.assertIn(
            'class="settings-field settings-field-wide" '
            'for="setting-soundtouch-cli-command"',
            index_html,
        )

    def test_settings_ui_uses_explicit_settings_and_status_endpoints(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('fetch("/api/settings")', app_js)
        self.assertIn('fetch("/api/settings", {', app_js)
        self.assertIn('method: "PUT"', app_js)
        self.assertIn('fetch("/api/components/status")', app_js)
        self.assertIn("data.restart_required", app_js)
        self.assertIn("settingsMessage.textContent = data.message;", app_js)

    def test_settings_dialog_is_phone_responsive(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertIn(".settings-dialog", styles_css)
        self.assertIn("width: min(42rem, calc(100% - 1.5rem));", styles_css)
        self.assertRegex(
            styles_css,
            r"@media \(max-width: 760px\)[\s\S]*?\.settings-fields\s*\{"
            r"[^}]*grid-template-columns: minmax\(0, 1fr\);",
        )
        self.assertRegex(
            styles_css,
            r"@media \(max-width: 760px\)[\s\S]*?\.settings-dialog\s*\{"
            r"[^}]*max-width: calc\(100% - 0\.75rem\);",
        )

    def test_settings_sections_use_compact_distinct_visual_styles(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertRegex(
            styles_css,
            r"\.settings-fields\s*\{[^}]*"
            r"grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);",
        )
        self.assertRegex(
            styles_css,
            r"\.settings-field-wide\s*\{[^}]*grid-column: 1 / -1;",
        )
        self.assertRegex(
            styles_css,
            r"\.component-status-list > div\s*\{[^}]*display: grid;"
            r"[^}]*grid-template-columns: minmax\(7rem, 0\.65fr\) minmax\(0, 1fr\);",
        )
        self.assertRegex(
            styles_css,
            r"\.settings-action-section\s*\{[^}]*background: var\(--surface-subtle\);",
        )
        self.assertRegex(
            styles_css,
            r"\.settings-dialog button:focus-visible,[\s\S]*?"
            r"outline-color: color-mix\(in srgb, var\(--accent\) 65%, transparent\);",
        )
        self.assertRegex(
            styles_css,
            r"@media \(max-width: 760px\)[\s\S]*?\.settings-field-wide\s*\{"
            r"[^}]*grid-column: auto;",
        )

    def test_settings_restart_requires_confirmation_and_explains_playback_stop(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('id="settings-restart-panel"', index_html)
        self.assertIn('id="settings-restart-button"', index_html)
        self.assertIn("Playback will stop briefly", index_html)
        self.assertIn("window.confirm(", app_js)
        self.assertIn("Playback will stop briefly while the service restarts", app_js)
        self.assertIn("if (!confirmed)", app_js)

    def test_settings_restart_disables_repeats_and_polls_health(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('fetch("/api/system/restart", {', app_js)
        self.assertIn('method: "POST"', app_js)
        self.assertIn("settingsRestartButton.disabled = true;", app_js)
        self.assertIn("await waitForApplicationHealth();", app_js)
        self.assertIn('fetch("/api/health", { cache: "no-store" })', app_js)
        self.assertIn("RESTART_HEALTH_POLL_INTERVAL_MS = 1500", app_js)
        self.assertIn("RESTART_HEALTH_TIMEOUT_MS = 45000", app_js)

    def test_settings_restart_timeout_is_reported_and_retry_is_enabled(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn(
            'throw new Error("The application did not come back online within 45 seconds")',
            app_js,
        )
        self.assertIn(
            "settingsMessage.textContent = `Could not restart TheCakeIsAPI: ${error.message}`;",
            app_js,
        )
        self.assertIn("settingsRestartButton.disabled = false;", app_js)

    def test_restart_action_is_shown_only_when_restart_is_required(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        app_js = APP_JS.read_text(encoding="utf-8")
        styles_css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertRegex(
            index_html,
            r'id="settings-restart-panel" class="settings-restart-panel" hidden',
        )
        self.assertIn("setRestartRequired(data.restart_required);", app_js)
        self.assertIn("settingsRestartPanel.hidden = !restartRequired;", app_js)
        self.assertIn(".settings-restart-panel[hidden]", styles_css)
        self.assertRegex(
            styles_css,
            r"@media \(max-width: 760px\)[\s\S]*?\.settings-restart-panel\s*\{"
            r"[^}]*flex-direction: column;",
        )


class WebUiBosePresetTests(unittest.TestCase):
    def test_bose_only_launcher_is_next_to_settings_with_accessible_svg(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        app_js = APP_JS.read_text(encoding="utf-8")

        launcher_position = index_html.index('id="bose-presets-button"')
        settings_position = index_html.index('id="settings-button"')
        self.assertLess(launcher_position, settings_position)
        self.assertIn('aria-label="Bose Presets"', index_html)
        self.assertIn('<svg class="topbar-button-icon"', index_html)
        self.assertIn(
            "/static/styles.css?v=__THECAKEISAPI_VERSION__&state=bose-controls",
            index_html,
        )
        self.assertIn(
            'bosePresetsButton.hidden = selectedOutput() !== "bose";',
            app_js,
        )
        self.assertIn("updateBosePresetsLauncher();", app_js)

    def test_dialog_enables_power_and_volume_but_keeps_aux_disabled(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        dialog_html = index_html.split(
            '<dialog id="bose-presets-dialog"',
            1,
        )[1].split("</dialog>", 1)[0]

        self.assertEqual(dialog_html.count('class="bose-preset-button"'), 6)
        for preset_id in range(1, 7):
            self.assertIn(f'data-preset-id="{preset_id}" disabled', dialog_html)
        self.assertEqual(dialog_html.count('class="bose-future-control"'), 3)
        self.assertIn('id="bose-power-button"', dialog_html)
        self.assertIn('id="bose-volume-up-button"', dialog_html)
        self.assertIn('id="bose-volume-down-button"', dialog_html)
        self.assertNotRegex(
            dialog_html,
            r'id="bose-(?:power|volume-up|volume-down)-button"[^>]*disabled',
        )
        self.assertIn('aria-label="Bluetooth and AUX unavailable"', dialog_html)
        self.assertRegex(
            dialog_html,
            r'class="bose-future-control bose-source-control"[^>]*disabled',
        )

    def test_remote_controls_post_one_allowlisted_action_per_click(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertEqual(
            app_js.count('fetch(`/api/player/bose/control/${action}`, {'),
            1,
        )
        self.assertIn('method: "POST"', app_js)
        self.assertEqual(
            app_js.count(
                'boseVolumeUpButton.addEventListener("click", () => '
                'sendBoseControlAction("volume-up"));'
            ),
            1,
        )
        self.assertEqual(
            app_js.count(
                'boseVolumeDownButton.addEventListener("click", () => '
                'sendBoseControlAction("volume-down"));'
            ),
            1,
        )
        control_handler = app_js.split(
            "async function sendBoseControlAction(action)",
            1,
        )[1].split("function closeBosePresetsFromBackdrop", 1)[0]
        self.assertNotIn("bosePresetsDialog.close();", control_handler)
        self.assertNotIn("Adjusting Bose volume", control_handler)
        self.assertNotIn("Sending Bose power command", control_handler)
        self.assertNotIn("Power command sent", control_handler)
        self.assertIn('if (action === "power") {', control_handler)
        self.assertIn("refreshPlaybackStatus();", control_handler)
        self.assertIn(
            "bosePresetsMessage.textContent = `Could not control Bose: ${error.message}`;",
            control_handler,
        )

    def test_power_requires_confirmation_before_sending_action(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")
        power_handler = app_js.split("function toggleBosePower()", 1)[1].split(
            "async function sendBoseControlAction(action)",
            1,
        )[0]

        self.assertIn("window.confirm(bosePowerConfirmationMessage())", power_handler)
        self.assertIn('sendBoseControlAction("power");', power_handler)
        self.assertLess(power_handler.index("return;"), power_handler.index('"power"'))
        self.assertEqual(
            app_js.count(
                'bosePowerButton.addEventListener("click", toggleBosePower);'
            ),
            1,
        )
        self.assertIn('return knownActivePlayback ? "Turn Bose off?" : "Toggle Bose power?";', app_js)

    def test_dialog_has_no_visible_header_or_close_button(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn(
            'class="bose-presets-dialog" aria-label="Bose Presets" tabindex="-1"',
            index_html,
        )
        self.assertNotIn('class="bose-presets-dialog-header"', index_html)
        self.assertNotIn('id="bose-presets-close-button"', index_html)
        self.assertNotIn("bosePresetsCloseButton", app_js)
        self.assertIn("bosePresetsDialog.focus();", app_js)

    def test_presets_are_loaded_only_when_the_dialog_opens(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertEqual(app_js.count('fetch("/api/player/bose/presets")'), 1)
        self.assertIn("bosePresetsDialog.showModal();", app_js)
        self.assertIn("loadBosePresets();", app_js)
        self.assertIn("renderBosePresets(data.presets || []);", app_js)
        self.assertIn('button.disabled = !available;', app_js)
        self.assertIn('resetBosePresetButtons("Unavailable");', app_js)
        self.assertNotIn("physical presets available", app_js)
        self.assertIn(
            'bosePresetsMessage.textContent = availableCount ? "" : '
            '"No physical presets are assigned";',
            app_js,
        )

    def test_preset_activation_posts_then_closes_and_refreshes_status(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn(
            'fetch(`/api/player/bose/presets/${presetId}/activate`, {',
            app_js,
        )
        self.assertIn('method: "POST"', app_js)
        self.assertIn("renderPlaybackState(data);", app_js)
        self.assertIn("bosePresetsDialog.close();", app_js)
        self.assertIn("refreshPlaybackStatus();", app_js)

    def test_popup_reuses_external_metadata_for_current_item(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn("<span>Now Playing</span>", index_html)
        self.assertNotIn("Current Bose item", index_html)
        self.assertIn('id="bose-current-item-title"', index_html)
        self.assertIn("playbackState?.bose?.external_playback_active", app_js)
        self.assertIn(
            'return playbackState.bose.external_display_name || "External Bose playback";',
            app_js,
        )
        self.assertIn(
            "boseCurrentItemTitle.textContent = currentBoseItemTitle(playbackState);",
            app_js,
        )
        self.assertRegex(
            STYLES_CSS.read_text(encoding="utf-8"),
            r"\.bose-current-item\s*\{[^}]*display: flex;[^}]*"
            r"justify-content: center;",
        )

    def test_backdrop_click_is_consumed_before_dialog_closes(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")
        handler = app_js.split(
            "function closeBosePresetsFromBackdrop(event)",
            1,
        )[1].split("function openSettings()", 1)[0]

        self.assertIn("event.target !== bosePresetsDialog", handler)
        self.assertIn("event.preventDefault();", handler)
        self.assertIn("event.stopPropagation();", handler)
        self.assertLess(handler.index("event.stopPropagation();"), handler.index(".close();"))

    def test_popup_keeps_remote_layout_and_truncation_on_narrow_screens(self) -> None:
        styles_css = STYLES_CSS.read_text(encoding="utf-8")
        mobile_rules = styles_css.split("@media (max-width: 760px)", 1)[1]
        mobile_rules = mobile_rules.split("@media (max-width: 420px)", 1)[0]

        self.assertRegex(
            styles_css,
            r"\.bose-remote-layout\s*\{[^}]*"
            r"grid-template-columns: 2\.8rem minmax\(0, 1fr\) 2\.8rem;[^}]*"
            r"gap: 0\.25rem;",
        )
        self.assertRegex(
            styles_css,
            r"\.bose-future-controls\s*\{[^}]*"
            r"grid-template-rows: repeat\(2, minmax\(4\.8rem, auto\)\);[^}]*"
            r"gap: 0\.5rem;",
        )
        self.assertRegex(
            styles_css,
            r"\.bose-future-control:first-child\s*\{[^}]*align-self: end;",
        )
        self.assertRegex(
            styles_css,
            r"\.bose-future-control:last-child\s*\{[^}]*align-self: start;",
        )
        self.assertRegex(
            styles_css,
            r"\.bose-preset-grid\s*\{[^}]*"
            r"grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);[^}]*"
            r"grid-template-rows: repeat\(2, minmax\(4\.8rem, auto\)\);",
        )
        self.assertIn("width: calc(100% - 0.5rem);", mobile_rules)
        self.assertIn("grid-template-columns: 2.75rem minmax(0, 1fr) 2.75rem;", mobile_rules)
        self.assertIn("grid-template-rows: repeat(2, minmax(4.15rem, auto));", mobile_rules)
        self.assertIn("gap: 0.2rem;", mobile_rules)
        self.assertIn("overflow-wrap: anywhere;", styles_css)
        self.assertIn("-webkit-line-clamp: 2;", styles_css)


if __name__ == "__main__":
    unittest.main()
