from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe
from threading import Event, Lock, Thread
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import __version__
from .bose import (
    BOSE_CONTROL_KEY_VALUES,
    BoseNowPlayingClient,
    BosePlaybackError,
    BosePlaybackState,
    SoundTouchCliClient,
    build_library_stream_url,
)
from .component_status import ComponentStatusProvider
from .configuration import (
    MAX_BOSE_POLL_INTERVAL_SECONDS,
    MIN_BOSE_POLL_INTERVAL_SECONDS,
    SettingsConfigurationStore,
    SettingsPersistenceError,
)
from .duration import audio_duration_seconds
from .library import (
    LibraryNotFoundError,
    LibraryPathError,
    UnsupportedAudioFileError,
    audio_media_type,
    get_library_status,
    list_directory,
    resolve_audio_file,
)
from .playlist import PlaybackQueue, QueueTrack
from .player import MpvPlayer, PlayerError
from .radio_presets import (
    RadioPresetNotFoundError,
    RadioPresetOrderConflictError,
    RadioPresetStorageError,
    RadioPresetStore,
    normalize_radio_name,
    normalize_radio_url,
)
from .restart import (
    ApplicationRestarter,
    RestartAlreadyScheduledError,
    RestartUnavailableError,
)
from .settings import Settings


BASE_DIR = Path(__file__).resolve().parent
WEBUI_DIR = BASE_DIR / "webui"
APP_VERSION_TOKEN = "__THECAKEISAPI_VERSION__"
BOSE_STATUS_FAILURE_THRESHOLD = 3


class PlayRequest(BaseModel):
    queue_paths: list[str] = Field(default_factory=list)


class QueueAddRequest(BaseModel):
    queue_paths: list[str] = Field(default_factory=list)


@dataclass
class LocalRadioState:
    stream_url: str
    display_name: str
    error_message: str | None = None


class LocalRadioPlayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    name: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return normalize_radio_url(value)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return normalize_radio_name(value)


class RadioPresetOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset_ids: list[UUID]


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bose_speaker_ip: str | None
    aftertouch_base_url: str | None
    soundtouch_cli_command: str
    public_base_url: str | None
    bose_state_poll_interval_seconds: float = Field(
        ge=MIN_BOSE_POLL_INTERVAL_SECONDS,
        le=MAX_BOSE_POLL_INTERVAL_SECONDS,
    )


class RestartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def create_app(
    settings: Settings | None = None,
    application_restarter: ApplicationRestarter | None = None,
) -> FastAPI:
    app_settings = settings or Settings.from_environment()

    app = FastAPI(
        title="thecakeisapi",
        description="Lightweight local music player for Raspberry Pi.",
        version=__version__,
    )
    app.state.settings = app_settings
    app.state.settings_store = SettingsConfigurationStore(app_settings)
    app.state.radio_preset_store = RadioPresetStore(
        app.state.settings_store.config_path.parent / "radio_presets.json",
    )
    app.state.component_status_provider = ComponentStatusProvider(
        __version__,
        app_settings.aftertouch_base_url,
        app_settings.soundtouch_cli_command,
    )
    app.state.application_restarter = (
        application_restarter or ApplicationRestarter.from_environment()
    )
    app.state.local_player = MpvPlayer(
        app_settings.mpv_command,
        app_settings.mpv_ipc_path,
    )
    app.state.bose_client = (
        SoundTouchCliClient(
            app_settings.soundtouch_cli_command,
            app_settings.bose_speaker_ip,
            app_settings.aftertouch_base_url,
        )
        if app_settings.bose_speaker_ip
        else None
    )
    app.state.bose_now_playing_client = (
        BoseNowPlayingClient(app_settings.bose_speaker_ip, app_settings.bose_api_port)
        if app_settings.bose_speaker_ip
        else None
    )
    app.state.playback_queue = PlaybackQueue()
    app.state.active_output = "local"
    app.state.local_radio_state = None
    app.state.bose_playback_state = BosePlaybackState()
    app.state.bose_playback_id_factory = lambda: token_urlsafe(18)
    app.state.repeat_track = False
    app.state.playback_message = "Stopped"
    app.state.playback_lock = Lock()
    app.state.playback_monitor_stop = Event()
    app.state.playback_monitor = Thread(
        target=_monitor_playback,
        args=(app,),
        daemon=True,
    )
    app.state.playback_monitor.start()

    app.mount(
        "/static",
        StaticFiles(directory=WEBUI_DIR / "static"),
        name="static",
    )

    @app.get("/", include_in_schema=False)
    def index() -> HTMLResponse:
        index_html = (WEBUI_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(
            index_html.replace(APP_VERSION_TOKEN, __version__),
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/settings")
    def read_settings() -> dict[str, object]:
        return app.state.settings_store.read()

    @app.put("/api/settings")
    def update_settings(request: SettingsUpdateRequest) -> dict[str, object]:
        try:
            saved_settings = app.state.settings_store.update(request.model_dump())
        except SettingsPersistenceError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        return {
            "settings": saved_settings,
            "restart_required": True,
            "message": (
                "Settings saved. Restart TheCakeIsAPI to apply the changes."
            ),
        }

    @app.get("/api/components/status")
    def component_status() -> dict[str, object]:
        return {
            "components": app.state.component_status_provider.get_status(),
        }

    @app.post("/api/system/restart", status_code=202)
    def restart_application(
        http_request: Request,
        _request: RestartRequest,
    ) -> dict[str, str]:
        if http_request.query_params:
            raise HTTPException(
                status_code=422,
                detail="Restart does not accept query parameters",
            )

        try:
            app.state.application_restarter.request_restart()
        except RestartAlreadyScheduledError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except RestartUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

        return {
            "status": "restarting",
            "message": "TheCakeIsAPI restart has been scheduled.",
        }

    @app.get("/api/library/status")
    def library_status() -> dict[str, object]:
        return get_library_status(app_settings.music_root)

    @app.get("/api/library/browse")
    def browse_library(path: str = "") -> dict[str, object]:
        try:
            return list_directory(app_settings.music_root, path)
        except LibraryPathError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LibraryNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/library/file")
    def stream_audio_file(path: str) -> FileResponse:
        try:
            file_path = resolve_audio_file(app_settings.music_root, path)
        except LibraryPathError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LibraryNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except UnsupportedAudioFileError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error

        return FileResponse(
            file_path,
            media_type=audio_media_type(file_path),
            filename=file_path.name,
        )

    @app.get("/api/player/bose/presets")
    def read_bose_presets() -> dict[str, object]:
        if app.state.bose_now_playing_client is None:
            raise HTTPException(
                status_code=503,
                detail="bose_speaker_ip is not configured",
            )

        try:
            presets = app.state.bose_now_playing_client.fetch_presets()
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

        return {"presets": [preset.as_dict() for preset in presets]}

    @app.post("/api/player/bose/presets/{preset_id}/activate")
    def activate_bose_preset(preset_id: int) -> dict[str, object]:
        if preset_id not in range(1, 7):
            raise HTTPException(
                status_code=400,
                detail="Bose preset id must be between 1 and 6",
            )

        try:
            with app.state.playback_lock:
                _select_bose_preset(app, preset_id)
                return _playback_status(app)
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/bose/control/{action}")
    def send_bose_control(action: str) -> dict[str, object]:
        if action not in BOSE_CONTROL_KEY_VALUES:
            raise HTTPException(
                status_code=400,
                detail="Unsupported Bose control action",
            )
        if app.state.bose_now_playing_client is None:
            raise HTTPException(
                status_code=503,
                detail="bose_speaker_ip is not configured",
            )

        try:
            with app.state.playback_lock:
                app.state.bose_now_playing_client.send_control_action(action)
                return _playback_status(app)
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/play")
    def play_local_file(
        path: str,
        request: PlayRequest | None = None,
    ) -> dict[str, object]:
        try:
            with app.state.playback_lock:
                queue_tracks = _validated_queue_tracks(
                    app_settings.music_root,
                    request.queue_paths if request else [],
                )
                selected_track = app.state.playback_queue.set_tracks(
                    queue_tracks,
                    path,
                    "local",
                )
                _play_track(app, selected_track)
                app.state.active_output = "local"
                app.state.playback_message = f"Playing {selected_track.name}"
                return _playback_status(app)
        except LibraryPathError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LibraryNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except UnsupportedAudioFileError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/radio/play")
    def play_local_radio(request: LocalRadioPlayRequest) -> dict[str, object]:
        try:
            with app.state.playback_lock:
                _play_local_radio(app, request.url, request.name)
                app.state.active_output = "local"
                app.state.playback_message = f"Playing live radio: {request.name}"
                return _playback_status(app)
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.get("/api/player/local/radio/presets")
    def read_local_radio_presets() -> dict[str, object]:
        try:
            presets = app.state.radio_preset_store.list_presets()
        except RadioPresetStorageError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {"presets": [preset.as_dict() for preset in presets]}

    @app.post("/api/player/local/radio/presets", status_code=201)
    def create_local_radio_preset(request: LocalRadioPlayRequest) -> dict[str, str]:
        try:
            preset = app.state.radio_preset_store.create(request.name, request.url)
        except RadioPresetStorageError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return preset.as_dict()

    @app.put("/api/player/local/radio/presets/order")
    def reorder_local_radio_presets(
        request: RadioPresetOrderRequest,
    ) -> dict[str, object]:
        try:
            presets = app.state.radio_preset_store.reorder(request.preset_ids)
        except RadioPresetOrderConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except RadioPresetStorageError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {"presets": [preset.as_dict() for preset in presets]}

    @app.post("/api/player/local/radio/presets/{preset_id}/play")
    def play_local_radio_preset(preset_id: UUID) -> dict[str, object]:
        try:
            preset = app.state.radio_preset_store.get(preset_id)
        except RadioPresetNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RadioPresetStorageError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

        try:
            with app.state.playback_lock:
                _play_local_radio(app, preset.url, preset.name)
                app.state.active_output = "local"
                app.state.playback_message = f"Playing live radio: {preset.name}"
                return _playback_status(app)
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.put("/api/player/local/radio/presets/{preset_id}")
    def update_local_radio_preset(
        preset_id: UUID,
        request: LocalRadioPlayRequest,
    ) -> dict[str, str]:
        try:
            preset = app.state.radio_preset_store.update(
                preset_id,
                request.name,
                request.url,
            )
        except RadioPresetNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RadioPresetStorageError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return preset.as_dict()

    @app.delete("/api/player/local/radio/presets/{preset_id}", status_code=204)
    def delete_local_radio_preset(preset_id: UUID) -> Response:
        try:
            app.state.radio_preset_store.delete(preset_id)
        except RadioPresetNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RadioPresetStorageError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return Response(status_code=204)

    @app.post("/api/player/bose/play")
    def play_bose_file(
        path: str,
        request: PlayRequest | None = None,
    ) -> dict[str, object]:
        try:
            with app.state.playback_lock:
                queue_tracks = _validated_queue_tracks(
                    app_settings.music_root,
                    request.queue_paths if request else [],
                )
                selected_track = app.state.playback_queue.set_tracks(
                    queue_tracks,
                    path,
                    "bose",
                )
                _play_bose_track(app, selected_track)
                app.state.active_output = "bose"
                app.state.playback_message = _bose_playback_message(selected_track.name, app)
                return _playback_status(app)
        except LibraryPathError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LibraryNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except UnsupportedAudioFileError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/bose/resume")
    def replay_current_bose_file() -> dict[str, object]:
        try:
            with app.state.playback_lock:
                if app.state.bose_playback_state.external_playback_active:
                    app.state.playback_message = "Bose playback is controlled externally"
                    return _playback_status(app)
                if app.state.bose_playback_state.state == "paused":
                    _resume_bose_playback(app)
                    app.state.active_output = "bose"
                    app.state.playback_message = "Restarted Bose playback; timer reset"
                    return _playback_status(app)

                current_track = app.state.playback_queue.current("bose")
                if current_track is None:
                    app.state.playback_message = "No track is selected"
                    return _playback_status(app)
                _play_bose_track(app, current_track)
                app.state.active_output = "bose"
                app.state.playback_message = _bose_playback_message(current_track.name, app)
                return _playback_status(app)
        except LibraryPathError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LibraryNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except UnsupportedAudioFileError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/bose/pause")
    def pause_bose_playback() -> dict[str, object]:
        try:
            with app.state.playback_lock:
                _pause_bose_playback(app)
                app.state.active_output = "bose"
                app.state.playback_message = "Paused Bose playback"
                return _playback_status(app)
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/bose/next")
    def play_next_bose_track() -> dict[str, object]:
        with app.state.playback_lock:
            if app.state.bose_playback_state.external_playback_active:
                app.state.playback_message = "Bose playback is controlled externally"
                return _playback_status(app)
            next_track = app.state.playback_queue.next("bose")
            if next_track is None:
                app.state.playback_message = "End of queue"
                return _playback_status(app)
            return _play_bose_queue_track(app, next_track)

    @app.post("/api/player/bose/previous")
    def play_previous_bose_track() -> dict[str, object]:
        with app.state.playback_lock:
            if app.state.bose_playback_state.external_playback_active:
                app.state.playback_message = "Bose playback is controlled externally"
                return _playback_status(app)
            previous_track = app.state.playback_queue.previous("bose")
            if previous_track is None:
                current_track = app.state.playback_queue.current("bose")
                if current_track is None:
                    app.state.playback_message = "No track is selected"
                    return _playback_status(app)
                app.state.playback_message = "Start of queue"
                return _play_bose_queue_track(app, current_track)
            return _play_bose_queue_track(app, previous_track)

    @app.post("/api/player/bose/stop")
    def stop_bose_playback() -> dict[str, object]:
        try:
            with app.state.playback_lock:
                stopped = _stop_bose_playback(app)
                app.state.active_output = "bose"
                app.state.playback_message = (
                    "Stopped Bose playback"
                    if stopped
                    else "Bose playback is controlled externally"
                )
                return _playback_status(app)
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/resume")
    def resume_local_playback() -> dict[str, object]:
        try:
            with app.state.playback_lock:
                if app.state.local_radio_state is not None:
                    app.state.playback_message = (
                        "Live radio must be started from its radio source"
                    )
                    return _playback_status(app)
                current_track = app.state.playback_queue.current("local")
                if app.state.local_player.status()["state"] == "stopped":
                    if current_track is None:
                        app.state.playback_message = "No track is selected"
                        return _playback_status(app)
                    _play_track(app, current_track)
                else:
                    app.state.local_player.resume()
                app.state.active_output = "local"
                app.state.playback_message = "Playing on Pi"
                return _playback_status(app)
        except LibraryPathError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LibraryNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except UnsupportedAudioFileError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/pause")
    def pause_local_playback() -> dict[str, object]:
        try:
            with app.state.playback_lock:
                if app.state.local_radio_state is not None:
                    app.state.playback_message = "Pause is unavailable for live radio"
                    return _playback_status(app)
                app.state.local_player.pause()
                app.state.playback_message = "Paused"
                return _playback_status(app)
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/stop")
    def stop_local_playback() -> dict[str, object]:
        with app.state.playback_lock:
            app.state.active_output = "local"
            stopped_radio = app.state.local_radio_state is not None
            app.state.local_player.stop()
            app.state.local_radio_state = None
            app.state.playback_message = (
                "Stopped live radio" if stopped_radio else "Stopped"
            )
            return _playback_status(app)

    @app.post("/api/player/local/seek")
    def seek_local_playback(seconds: float) -> dict[str, object]:
        try:
            with app.state.playback_lock:
                if app.state.local_radio_state is not None:
                    app.state.playback_message = "Seeking is unavailable for live radio"
                    return _playback_status(app)
                app.state.local_player.seek(seconds)
                app.state.playback_message = f"Seeked to {int(max(0, seconds))} seconds"
                return _playback_status(app)
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/next")
    def play_next_local_track() -> dict[str, object]:
        with app.state.playback_lock:
            if app.state.local_radio_state is not None:
                app.state.playback_message = "Next is unavailable for live radio"
                return _playback_status(app)
            next_track = app.state.playback_queue.next("local")
            if next_track is None:
                app.state.local_player.stop()
                app.state.playback_message = "End of queue"
                return _playback_status(app)
            return _play_queue_track(app, next_track)

    @app.post("/api/player/local/previous")
    def play_previous_local_track() -> dict[str, object]:
        with app.state.playback_lock:
            if app.state.local_radio_state is not None:
                app.state.playback_message = "Previous is unavailable for live radio"
                return _playback_status(app)
            previous_track = app.state.playback_queue.previous("local")
            if previous_track is None:
                current_track = app.state.playback_queue.current("local")
                if current_track is None:
                    app.state.playback_message = "No track is selected"
                    return _playback_status(app)
                app.state.playback_message = "Start of queue"
                try:
                    _play_track(app, current_track)
                except LibraryPathError as error:
                    raise HTTPException(status_code=400, detail=str(error)) from error
                except LibraryNotFoundError as error:
                    raise HTTPException(status_code=404, detail=str(error)) from error
                except UnsupportedAudioFileError as error:
                    raise HTTPException(status_code=415, detail=str(error)) from error
                except BosePlaybackError as error:
                    raise HTTPException(status_code=503, detail=str(error)) from error
                except PlayerError as error:
                    raise HTTPException(status_code=503, detail=str(error)) from error
                return _playback_status(app)
            return _play_queue_track(app, previous_track)

    @app.post("/api/player/local/repeat")
    def set_repeat_track(enabled: bool) -> dict[str, object]:
        with app.state.playback_lock:
            if app.state.local_radio_state is not None:
                app.state.playback_message = "Repeat is unavailable for live radio"
                return _playback_status(app)
            app.state.repeat_track = enabled
            app.state.playback_message = (
                "Repeat track on" if app.state.repeat_track else "Repeat track off"
            )
            return _playback_status(app)

    @app.post("/api/player/local/queue/clear")
    def clear_local_queue() -> dict[str, object]:
        try:
            with app.state.playback_lock:
                if app.state.bose_playback_state.has_app_ownership_context:
                    _stop_bose_playback(app)
                app.state.playback_queue.clear()
                app.state.local_player.stop()
                app.state.local_radio_state = None
                app.state.playback_message = "Queue cleared"
                return _playback_status(app)
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/queue/add")
    def add_local_queue_tracks(request: QueueAddRequest) -> dict[str, object]:
        try:
            with app.state.playback_lock:
                queue_tracks = _validated_queue_tracks(
                    app_settings.music_root,
                    request.queue_paths,
                )
                app.state.playback_queue.add_tracks(queue_tracks)
                app.state.playback_message = (
                    f"Added {len(queue_tracks)} track to queue"
                    if len(queue_tracks) == 1
                    else f"Added {len(queue_tracks)} tracks to queue"
                )
                return _playback_status(app)
        except LibraryPathError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LibraryNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except UnsupportedAudioFileError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error

    @app.post("/api/player/local/queue/remove")
    def remove_local_queue_track(path: str) -> dict[str, object]:
        with app.state.playback_lock:
            local_status = app.state.local_player.status()
            bose_state = app.state.bose_playback_state
            local_was_playing_removed_track = _local_status_matches_track(
                app,
                local_status,
                path,
            )
            bose_was_playing_removed_track = (
                bose_state.state in {"starting", "playing", "paused"}
                and bose_state.has_app_ownership_context
                and not bose_state.external_playback_active
                and bose_state.track_path == path
            )

            removal = app.state.playback_queue.remove(path)
            playback_errors: list[Exception] = []

            if removal.local.removed_current and local_was_playing_removed_track:
                try:
                    if removal.local.current_track is None:
                        app.state.local_player.stop()
                    else:
                        _play_track(app, removal.local.current_track)
                except (
                    LibraryPathError,
                    LibraryNotFoundError,
                    UnsupportedAudioFileError,
                    PlayerError,
                ) as error:
                    playback_errors.append(error)

            if removal.bose.removed_current and bose_was_playing_removed_track:
                try:
                    if removal.bose.current_track is None:
                        _stop_bose_playback(app)
                    else:
                        _play_bose_track(app, removal.bose.current_track)
                except (
                    LibraryPathError,
                    LibraryNotFoundError,
                    UnsupportedAudioFileError,
                    BosePlaybackError,
                ) as error:
                    playback_errors.append(error)

            if playback_errors:
                _raise_playback_http_exception(playback_errors[0])

            queue_is_empty = not app.state.playback_queue.as_dict(
                app.state.active_output,
            )["tracks"]
            app.state.playback_message = (
                "Queue empty" if removal.removed and queue_is_empty
                else "Removed track from queue"
            )
            return _playback_status(app)

    @app.post("/api/player/local/queue/move-up")
    def move_local_queue_track_up(path: str) -> dict[str, object]:
        with app.state.playback_lock:
            moved = app.state.playback_queue.move_up(path)
            app.state.playback_message = "Moved track up" if moved else "Track is already first"
            return _playback_status(app)

    @app.post("/api/player/local/queue/move-down")
    def move_local_queue_track_down(path: str) -> dict[str, object]:
        with app.state.playback_lock:
            moved = app.state.playback_queue.move_down(path)
            app.state.playback_message = "Moved track down" if moved else "Track is already last"
            return _playback_status(app)

    @app.get("/api/player/local/status")
    def local_playback_status() -> dict[str, object]:
        with app.state.playback_lock:
            _sync_finished_playback(app)
            return _playback_status(app)

    @app.get("/api/player/status")
    def playback_status(observe_bose: bool = False) -> dict[str, object]:
        with app.state.playback_lock:
            _sync_finished_playback(app)
            if observe_bose:
                _observe_external_bose_playback(app)
            return _playback_status(app)

    return app


def _validated_queue_tracks(music_root: Path, queue_paths: list[str]) -> list[QueueTrack]:
    tracks: list[QueueTrack] = []
    for path in queue_paths:
        file_path = resolve_audio_file(music_root, path)
        tracks.append(QueueTrack(path=path, name=file_path.name))
    return tracks


def _local_status_matches_track(
    app: FastAPI,
    player_status: dict[str, object],
    track_path: str,
) -> bool:
    if player_status.get("state") not in {"playing", "paused"}:
        return False

    current_path = player_status.get("path")
    if not current_path:
        return False

    try:
        relative_path = Path(str(current_path)).resolve().relative_to(
            app.state.settings.music_root.resolve(),
        )
    except (OSError, ValueError):
        return False

    return relative_path.as_posix() == track_path


def _raise_playback_http_exception(error: Exception) -> None:
    status_code = 503
    if isinstance(error, LibraryPathError):
        status_code = 400
    elif isinstance(error, LibraryNotFoundError):
        status_code = 404
    elif isinstance(error, UnsupportedAudioFileError):
        status_code = 415
    raise HTTPException(status_code=status_code, detail=str(error)) from error


def _play_queue_track(app: FastAPI, track: QueueTrack | None) -> dict[str, object]:
    if track is None:
        app.state.active_output = "local"
        app.state.local_player.stop()
        app.state.playback_message = "End of queue"
        return _playback_status(app)

    try:
        _play_track(app, track)
        app.state.active_output = "local"
        app.state.playback_message = f"Playing {track.name}"
        return _playback_status(app)
    except LibraryPathError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except LibraryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UnsupportedAudioFileError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except BosePlaybackError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except PlayerError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _play_bose_queue_track(app: FastAPI, track: QueueTrack) -> dict[str, object]:
    try:
        _play_bose_track(app, track)
        app.state.active_output = "bose"
        app.state.playback_message = _bose_playback_message(track.name, app)
        return _playback_status(app)
    except LibraryPathError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except LibraryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UnsupportedAudioFileError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except BosePlaybackError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _play_track(app: FastAPI, track: QueueTrack) -> None:
    file_path = resolve_audio_file(app.state.settings.music_root, track.path)
    app.state.local_radio_state = None
    app.state.local_player.play(file_path)


def _play_local_radio(app: FastAPI, stream_url: str, display_name: str) -> None:
    radio_state = LocalRadioState(
        stream_url=stream_url,
        display_name=display_name,
    )
    app.state.local_radio_state = radio_state
    try:
        app.state.local_player.play(stream_url)
    except PlayerError as error:
        radio_state.error_message = str(error)
        app.state.playback_message = f"Could not start live radio: {display_name}"
        raise


def _select_bose_preset(app: FastAPI, preset_id: int) -> None:
    if preset_id not in range(1, 7):
        raise BosePlaybackError("Bose preset id must be between 1 and 6")
    if app.state.bose_now_playing_client is None:
        raise BosePlaybackError("bose_speaker_ip is not configured")

    app.state.playback_queue.clear_cursor("bose")
    app.state.bose_playback_state = BosePlaybackState()
    app.state.active_output = "bose"

    try:
        app.state.bose_now_playing_client.select_preset(preset_id)
    except BosePlaybackError:
        app.state.bose_playback_state.externally_stopped(
            "Bose preset selection failed; playback ownership cleared",
        )
        app.state.playback_message = "Bose preset selection failed"
        raise

    app.state.bose_playback_state.externally_active(
        f"Bose preset {preset_id} selected",
        source="PRESET",
    )
    app.state.bose_playback_state.last_status_poll_monotonic = None
    app.state.playback_message = f"Selected Bose preset {preset_id}"


def _bose_playback_message(track_name: str, app: FastAPI) -> str:
    if app.state.bose_playback_state.warning:
        return f"Bose playback started with warning: {app.state.bose_playback_state.warning}"
    if app.state.bose_playback_state.state == "starting":
        return f"Starting on Bose: {track_name}"
    return f"Playing on Bose: {track_name}"


def _play_bose_track(app: FastAPI, track: QueueTrack) -> None:
    if app.state.bose_client is None:
        if not app.state.settings.bose_speaker_ip:
            raise BosePlaybackError("bose_speaker_ip is not configured")
        raise BosePlaybackError("aftertouch_base_url is not configured")

    if not app.state.settings.public_base_url:
        raise BosePlaybackError("public_base_url is not configured")

    file_path = resolve_audio_file(app.state.settings.music_root, track.path)
    stream_url = build_library_stream_url(app.state.settings.public_base_url, track.path)
    ownership_stream_url = build_library_stream_url(
        app.state.settings.public_base_url,
        track.path,
        playback_id=app.state.bose_playback_id_factory(),
    )
    duration_seconds = audio_duration_seconds(file_path)

    app.state.bose_playback_state = BosePlaybackState(
        track_path=track.path,
        track_name=track.name,
        state="starting",
        start_timestamp=_current_timestamp(),
        paused_elapsed_seconds=None,
        duration_seconds=duration_seconds,
        stream_url=stream_url,
        ownership_stream_url=ownership_stream_url,
    )

    previous_now_playing = _fetch_bose_now_playing(app)
    playback_request = app.state.bose_client.play_stream(track.name, ownership_stream_url)
    app.state.bose_playback_state.command = playback_request.command

    confirmed_now_playing = _confirm_bose_playback_started(app, previous_now_playing)
    if confirmed_now_playing is None:
        if not app.state.bose_playback_state.warning:
            app.state.bose_playback_state.warning = (
                "Bose playback command was sent, but now_playing confirmation timed out"
            )
        return

    app.state.bose_playback_state.record_status_poll_started()
    app.state.bose_playback_state.record_status_poll_success()
    app.state.bose_playback_state.confirm_ownership()
    app.state.bose_playback_state.state = "playing"
    app.state.bose_playback_state.confirmed_start_timestamp = _current_timestamp()


def _stop_bose_playback(app: FastAPI) -> bool:
    if app.state.bose_client is None:
        raise BosePlaybackError("bose_speaker_ip is not configured")

    playback_state = app.state.bose_playback_state
    if not playback_state.has_app_ownership_context:
        return False

    if playback_state.ownership_confirmed and app.state.bose_now_playing_client:
        try:
            status = app.state.bose_now_playing_client.fetch_status()
        except BosePlaybackError as error:
            raise BosePlaybackError(
                "Could not confirm Bose playback ownership before stopping",
            ) from error

        if status.appears_to_be_invalid_source or not status.source:
            raise BosePlaybackError(
                "Could not confirm Bose playback ownership before stopping",
            )

        if not (
            status.appears_to_be_custom_radio
            and status.matches_stream_url(playback_state.ownership_stream_url or "")
        ):
            reason = "Bose playback is active externally"
            if status.appears_to_be_stopped:
                reason = "Bose playback stopped externally"
                playback_state.externally_stopped(reason)
            else:
                if status.source:
                    reason = f"{reason} on {status.source}"
                playback_state.externally_active(
                    reason,
                    display_name=status.display_name,
                    source=status.source,
                )
            app.state.playback_message = reason
            return False

    app.state.bose_client.stop()
    playback_state.stop()
    return True


def _pause_bose_playback(app: FastAPI) -> None:
    if app.state.bose_client is None:
        raise BosePlaybackError("bose_speaker_ip is not configured")

    if (
        app.state.bose_playback_state.state != "playing"
        or not app.state.bose_playback_state.has_app_ownership_context
    ):
        return

    app.state.bose_client.pause()
    app.state.bose_playback_state.pause()


def _resume_bose_playback(app: FastAPI) -> None:
    if app.state.bose_client is None:
        raise BosePlaybackError("bose_speaker_ip is not configured")

    if (
        app.state.bose_playback_state.state != "paused"
        or not app.state.bose_playback_state.has_app_ownership_context
    ):
        return

    app.state.bose_client.resume()
    app.state.bose_playback_state.resume_from_start()


def _sync_finished_playback(app: FastAPI) -> None:
    _sync_local_playback(app)
    _sync_bose_playback(app)


def _sync_local_playback(app: FastAPI) -> None:
    if not app.state.local_player.consume_finished():
        return

    radio_state = app.state.local_radio_state
    if radio_state is not None:
        radio_state.error_message = "Live radio playback stopped unexpectedly"
        app.state.playback_message = radio_state.error_message
        return

    current_track = app.state.playback_queue.current("local")
    if current_track is None:
        app.state.playback_message = "Stopped"
        return

    if app.state.repeat_track:
        try:
            _play_track(app, current_track)
            app.state.playback_message = f"Repeating {current_track.name}"
        except (LibraryPathError, LibraryNotFoundError, UnsupportedAudioFileError, PlayerError):
            app.state.playback_message = "Could not repeat track"
        return

    next_track = app.state.playback_queue.next("local")
    if next_track is None:
        app.state.playback_message = "End of queue"
        return

    try:
        _play_track(app, next_track)
        app.state.playback_message = f"Playing {next_track.name}"
    except (LibraryPathError, LibraryNotFoundError, UnsupportedAudioFileError, PlayerError):
        app.state.playback_message = "Could not start next track"


def _monitor_playback(app: FastAPI) -> None:
    while not app.state.playback_monitor_stop.wait(1):
        with app.state.playback_lock:
            _sync_finished_playback(app)


def _sync_bose_playback(app: FastAPI) -> None:
    transition_due = (
        app.state.bose_playback_state.ownership_confirmed
        and app.state.bose_playback_state.should_auto_advance(
            app.state.settings.bose_auto_advance_buffer_seconds,
        )
    )
    transition_source_gap = _poll_bose_playback_state(
        app,
        allow_app_transition_source_gap=transition_due,
    )
    if (
        app.state.bose_playback_state.status_poll_failures > 0
        and not transition_source_gap
    ):
        return

    if not app.state.bose_playback_state.ownership_confirmed:
        return

    if not app.state.bose_playback_state.should_auto_advance(
        app.state.settings.bose_auto_advance_buffer_seconds,
    ):
        return

    current_track = app.state.playback_queue.current("bose")
    if current_track is None:
        app.state.bose_playback_state.ended()
        app.state.playback_message = "End of queue"
        return

    if app.state.repeat_track:
        try:
            _play_bose_track(app, current_track)
            app.state.playback_message = f"Repeating on Bose: {current_track.name}"
        except (LibraryPathError, LibraryNotFoundError, UnsupportedAudioFileError, BosePlaybackError):
            app.state.bose_playback_state.error("Could not repeat Bose track")
            app.state.playback_message = "Could not repeat Bose track"
        return

    next_track = app.state.playback_queue.next("bose")
    if next_track is None:
        app.state.bose_playback_state.ended()
        app.state.playback_message = "End of queue"
        return

    try:
        _play_bose_track(app, next_track)
        app.state.playback_message = f"Playing on Bose: {next_track.name}"
    except (LibraryPathError, LibraryNotFoundError, UnsupportedAudioFileError, BosePlaybackError):
        app.state.bose_playback_state.error("Could not start next Bose track")
        app.state.playback_message = "Could not start next Bose track"


def _poll_bose_playback_state(
    app: FastAPI,
    now_monotonic: float | None = None,
    allow_app_transition_source_gap: bool = False,
) -> bool:
    """Return whether an expected app-initiated transition gap was observed."""
    playback_state = app.state.bose_playback_state
    if playback_state.state not in {"starting", "playing", "paused"}:
        return False
    if app.state.bose_now_playing_client is None:
        return False
    if not playback_state.status_poll_due(
        app.state.settings.bose_state_poll_interval_seconds,
        now_monotonic,
    ):
        return False

    playback_state.record_status_poll_started(now_monotonic)
    try:
        status = app.state.bose_now_playing_client.fetch_status()
    except BosePlaybackError:
        _record_bose_status_poll_failure(app, "Bose speaker is unavailable")
        return False

    if status.appears_to_be_invalid_source:
        if allow_app_transition_source_gap:
            return True
        _record_bose_status_poll_failure(app, "Bose source transition did not settle")
        return False

    if status.appears_to_be_custom_radio and not status.matches_stream_url(
        playback_state.ownership_stream_url or "",
    ):
        playback_state.record_status_poll_success()
        if status.appears_to_be_stopped:
            reason = "Bose playback stopped externally"
            playback_state.externally_stopped(reason)
        else:
            reason = "Bose playback is active externally"
            if status.source:
                reason = f"{reason} on {status.source}"
            playback_state.externally_active(
                reason,
                display_name=status.display_name,
                source=status.source,
            )
        app.state.playback_message = reason
        return False

    if status.appears_to_be_stopped:
        playback_state.record_status_poll_success()
        if (
            status.appears_to_be_custom_radio
            and not status.appears_to_be_standby
            and (
                playback_state.state == "paused"
                or _bose_track_reached_estimated_end(playback_state)
            )
        ):
            return False
        reason = "Bose playback stopped externally"
        playback_state.externally_stopped(reason)
        app.state.playback_message = reason
        return False

    if status.appears_to_be_custom_radio:
        playback_state.record_status_poll_success()
        playback_state.confirm_ownership()
        if playback_state.state == "starting":
            playback_state.state = "playing"
            playback_state.confirmed_start_timestamp = _current_timestamp()
            app.state.playback_message = f"Playing on Bose: {playback_state.track_name}"
        return False

    if status.source:
        playback_state.record_status_poll_success()
        reason = f"Bose playback is active externally on {status.source}"
        playback_state.externally_active(
            reason,
            display_name=status.display_name,
            source=status.source,
        )
        app.state.playback_message = reason
        return False

    if allow_app_transition_source_gap:
        return True

    _record_bose_status_poll_failure(app, "Bose status could not be confirmed")
    return False


def _bose_track_reached_estimated_end(playback_state: BosePlaybackState) -> bool:
    if playback_state.duration_seconds is None:
        return False
    elapsed_seconds = playback_state.elapsed_seconds()
    return elapsed_seconds is not None and elapsed_seconds >= playback_state.duration_seconds


def _observe_external_bose_playback(
    app: FastAPI,
    now_monotonic: float | None = None,
) -> None:
    playback_state = app.state.bose_playback_state
    if app.state.bose_now_playing_client is None:
        return
    if (
        playback_state.has_app_ownership_context
        and playback_state.state in {"starting", "playing", "paused"}
    ):
        _poll_bose_playback_state(app, now_monotonic=now_monotonic)
        return
    if playback_state.state in {"starting", "playing", "paused"}:
        return
    if not playback_state.status_poll_due(
        app.state.settings.bose_state_poll_interval_seconds,
        now_monotonic,
    ):
        return

    playback_state.record_status_poll_started(now_monotonic)
    try:
        status = app.state.bose_now_playing_client.fetch_status()
    except BosePlaybackError:
        _record_external_bose_poll_failure(playback_state)
        return

    if status.appears_to_be_invalid_source or not status.source:
        _record_external_bose_poll_failure(playback_state)
        return

    playback_state.record_status_poll_success()
    if status.appears_to_be_stopped:
        playback_state.externally_stopped("Bose playback stopped externally")
        return

    playback_state.externally_active(
        "Bose playback is active externally",
        display_name=status.display_name,
        source=status.source,
    )


def _record_external_bose_poll_failure(playback_state: BosePlaybackState) -> None:
    if playback_state.record_status_poll_failure() < BOSE_STATUS_FAILURE_THRESHOLD:
        return
    playback_state.externally_stopped("Bose speaker is unavailable")


def _record_bose_status_poll_failure(app: FastAPI, reason: str) -> None:
    playback_state = app.state.bose_playback_state
    failures = playback_state.record_status_poll_failure()
    if failures < BOSE_STATUS_FAILURE_THRESHOLD:
        return

    message = f"{reason}; playback state cleared"
    playback_state.externally_stopped(message)
    app.state.playback_message = message


def _playback_status(app: FastAPI) -> dict[str, object]:
    output_statuses = {
        "local": _local_output_status(app),
        "bose": _bose_output_status(app),
    }
    player_status = output_statuses.get(
        app.state.active_output,
        output_statuses["local"],
    )
    queue_status = app.state.playback_queue.as_dict(app.state.active_output)
    current_track = app.state.playback_queue.current(app.state.active_output)
    if (
        app.state.active_output == "bose"
        and app.state.bose_playback_state.external_playback_active
    ):
        current_track = None
    legacy_now_playing = (
        {
            "path": current_track.path,
            "name": current_track.name,
        }
        if current_track
        else None
    )
    if (
        app.state.active_output == "local"
        and player_status.get("source_type") == "radio"
    ):
        legacy_now_playing = player_status["now_playing"]

    return {
        "active_output": app.state.active_output,
        "backend": player_status["backend"],
        "state": player_status["state"],
        "process_id": player_status["process_id"],
        "elapsed_seconds": player_status["elapsed_seconds"],
        "duration_seconds": player_status["duration_seconds"],
        "paused": player_status["paused"],
        "repeat_track": app.state.repeat_track,
        "message": app.state.playback_message,
        "now_playing": legacy_now_playing,
        "queue": queue_status["tracks"],
        "outputs": output_statuses,
        "bose": {
            "speaker_ip": app.state.settings.bose_speaker_ip,
            "api_port": app.state.settings.bose_api_port,
            "aftertouch_base_url": app.state.settings.aftertouch_base_url,
            "public_base_url": app.state.settings.public_base_url,
            "track_path": app.state.bose_playback_state.track_path,
            "track_name": app.state.bose_playback_state.track_name,
            "state": app.state.bose_playback_state.state,
            "start_timestamp": app.state.bose_playback_state.start_timestamp,
            "confirmed_start_timestamp": (
                app.state.bose_playback_state.confirmed_start_timestamp
            ),
            "paused_elapsed_seconds": app.state.bose_playback_state.paused_elapsed_seconds,
            "elapsed_seconds": app.state.bose_playback_state.elapsed_seconds(),
            "duration_seconds": app.state.bose_playback_state.duration_seconds,
            "stream_url": app.state.bose_playback_state.stream_url,
            "command": app.state.bose_playback_state.command,
            "warning": app.state.bose_playback_state.warning,
            "last_confirmed_status_timestamp": (
                app.state.bose_playback_state.last_confirmed_status_timestamp
            ),
            "status_poll_failures": app.state.bose_playback_state.status_poll_failures,
            "external_playback_active": (
                app.state.bose_playback_state.external_playback_active
            ),
            "external_display_name": (
                app.state.bose_playback_state.external_display_name
            ),
            "external_source": app.state.bose_playback_state.external_source,
        },
    }


def _active_player_status(app: FastAPI) -> dict[str, object]:
    if app.state.active_output == "bose":
        return _bose_output_status(app)

    return _local_output_status(app)


def _local_output_status(app: FastAPI) -> dict[str, object]:
    player_status = app.state.local_player.status()
    state = str(player_status["state"])
    radio_state = app.state.local_radio_state
    if radio_state is not None:
        if radio_state.error_message:
            state = "error"
        now_playing = None
        if state in {"playing", "paused"}:
            now_playing = {
                "path": None,
                "name": radio_state.display_name,
            }
        return {
            "backend": player_status["backend"],
            "state": state,
            "process_id": player_status["process_id"],
            "elapsed_seconds": None,
            "duration_seconds": None,
            "paused": False,
            "source_type": "radio",
            "source_name": radio_state.display_name,
            "now_playing": now_playing,
            "message": _output_playback_message(app, "local", state),
        }

    now_playing = None
    source_type = "none"
    source_name = None
    current_path = player_status.get("path")
    if state in {"playing", "paused"} and current_path:
        media_path = Path(str(current_path))
        try:
            relative_path = media_path.resolve().relative_to(
                app.state.settings.music_root.resolve(),
            )
        except (OSError, ValueError):
            relative_path = None

        if relative_path is not None:
            source_type = "library"
            source_name = media_path.name
            now_playing = {
                "path": relative_path.as_posix(),
                "name": media_path.name,
            }

    return {
        "backend": player_status["backend"],
        "state": state,
        "process_id": player_status["process_id"],
        "elapsed_seconds": player_status["elapsed_seconds"],
        "duration_seconds": player_status["duration_seconds"],
        "paused": player_status["paused"],
        "source_type": source_type,
        "source_name": source_name,
        "now_playing": now_playing,
        "message": _output_playback_message(app, "local", state),
    }


def _bose_output_status(app: FastAPI) -> dict[str, object]:
    playback_state = app.state.bose_playback_state
    now_playing = None
    if playback_state.external_playback_active:
        external_name = (
            playback_state.external_display_name
            or playback_state.external_source
            or "Bose"
        )
        now_playing = {
            "path": None,
            "name": external_name,
        }
    elif playback_state.state in {"starting", "playing", "paused"} and (
        playback_state.track_path or playback_state.track_name
    ):
        now_playing = {
            "path": playback_state.track_path,
            "name": playback_state.track_name
            or Path(playback_state.track_path or "").name,
        }

    return {
        "backend": "bose_aftertouch",
        "state": playback_state.state,
        "process_id": None,
        "elapsed_seconds": playback_state.elapsed_seconds(),
        "duration_seconds": playback_state.duration_seconds,
        "paused": playback_state.state == "paused",
        "now_playing": now_playing,
        "message": _output_playback_message(
            app,
            "bose",
            playback_state.state,
            external_playback_active=playback_state.external_playback_active,
        ),
        "external_playback_active": playback_state.external_playback_active,
        "external_display_name": playback_state.external_display_name,
        "external_source": playback_state.external_source,
    }


def _output_playback_message(
    app: FastAPI,
    output: str,
    state: str,
    external_playback_active: bool = False,
) -> str:
    if external_playback_active:
        return "External Bose playback"

    if output == "bose":
        state_messages = {
            "starting": (
                f"Starting on Bose: {app.state.bose_playback_state.track_name}"
            ),
            "playing": (
                f"Playing on Bose: {app.state.bose_playback_state.track_name}"
            ),
            "paused": "Paused Bose playback",
            "ended": "End of queue",
            "error": app.state.bose_playback_state.warning or "Bose playback error",
        }
        return state_messages.get(state, "Stopped Bose playback")

    radio_state = app.state.local_radio_state
    if radio_state is not None:
        if radio_state.error_message:
            return radio_state.error_message
        if state == "playing":
            return f"Playing live radio on Pi: {radio_state.display_name}"
        return "Live radio stopped"

    state_messages = {
        "playing": "Playing on Pi",
        "paused": "Paused",
    }
    return state_messages.get(state, "Stopped")


def _fetch_bose_now_playing(app: FastAPI):
    if app.state.bose_now_playing_client is None:
        return None

    try:
        return app.state.bose_now_playing_client.fetch_status()
    except BosePlaybackError:
        return None


def _confirm_bose_playback_started(app: FastAPI, previous_now_playing):
    if app.state.bose_now_playing_client is None:
        return None

    try:
        return app.state.bose_now_playing_client.wait_for_custom_radio(
            app.state.settings.bose_start_confirm_timeout_seconds,
            app.state.settings.bose_start_poll_interval_seconds,
            previous_now_playing,
            app.state.bose_playback_state.ownership_stream_url,
        )
    except BosePlaybackError as error:
        app.state.bose_playback_state.warning = str(error)
        return None


def _current_timestamp() -> float:
    from time import time

    return time()


app = create_app()
