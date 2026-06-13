from pathlib import Path
from threading import Event, Lock, Thread

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .bose import BosePlaybackError, SoundTouchCliClient, build_library_stream_url
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
from .settings import Settings


BASE_DIR = Path(__file__).resolve().parent
WEBUI_DIR = BASE_DIR / "webui"


class PlayRequest(BaseModel):
    queue_paths: list[str] = Field(default_factory=list)


class QueueAddRequest(BaseModel):
    queue_paths: list[str] = Field(default_factory=list)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_environment()

    app = FastAPI(
        title="thecakeisapi",
        description="Lightweight local music player for Raspberry Pi.",
        version="0.1.0",
    )
    app.state.settings = app_settings
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
    app.state.playback_queue = PlaybackQueue()
    app.state.active_output = "local"
    app.state.bose_playing = False
    app.state.bose_playback = None
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
    def index() -> FileResponse:
        return FileResponse(WEBUI_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/settings")
    def read_settings() -> dict[str, str | int | None]:
        return app_settings.as_dict()

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
                selected_track = app.state.playback_queue.set_tracks(queue_tracks, path)
                app.state.active_output = "local"
                _play_track(app, selected_track)
                app.state.playback_message = f"Playing {selected_track.name}"
                return _playback_status(app)
        except LibraryPathError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LibraryNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except UnsupportedAudioFileError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

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
                selected_track = app.state.playback_queue.set_tracks(queue_tracks, path)
                _play_bose_track(app, selected_track)
                app.state.active_output = "bose"
                app.state.local_player.stop()
                app.state.playback_message = f"Playing on Bose: {selected_track.name}"
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
                current_track = app.state.playback_queue.current()
                if current_track is None:
                    app.state.playback_message = "No track is selected"
                    return _playback_status(app)
                _play_bose_track(app, current_track)
                app.state.active_output = "bose"
                app.state.local_player.stop()
                app.state.playback_message = f"Playing on Bose: {current_track.name}"
                return _playback_status(app)
        except LibraryPathError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LibraryNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except UnsupportedAudioFileError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/bose/next")
    def play_next_bose_track() -> dict[str, object]:
        with app.state.playback_lock:
            next_track = app.state.playback_queue.next()
            if next_track is None:
                app.state.playback_message = "End of queue"
                return _playback_status(app)
            return _play_bose_queue_track(app, next_track)

    @app.post("/api/player/bose/previous")
    def play_previous_bose_track() -> dict[str, object]:
        with app.state.playback_lock:
            previous_track = app.state.playback_queue.previous()
            if previous_track is None:
                current_track = app.state.playback_queue.current()
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
                _stop_bose_playback(app)
                app.state.active_output = "bose"
                app.state.playback_message = "Stopped Bose playback"
                return _playback_status(app)
        except BosePlaybackError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/resume")
    def resume_local_playback() -> dict[str, object]:
        try:
            with app.state.playback_lock:
                current_track = app.state.playback_queue.current()
                app.state.active_output = "local"
                if app.state.local_player.status()["state"] == "stopped":
                    if current_track is None:
                        app.state.playback_message = "No track is selected"
                        return _playback_status(app)
                    _play_track(app, current_track)
                else:
                    app.state.local_player.resume()
                app.state.playback_message = "Playing on Pi"
                return _playback_status(app)
        except LibraryPathError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LibraryNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except UnsupportedAudioFileError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/pause")
    def pause_local_playback() -> dict[str, object]:
        try:
            with app.state.playback_lock:
                app.state.local_player.pause()
                app.state.playback_message = "Paused"
                return _playback_status(app)
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/stop")
    def stop_local_playback() -> dict[str, object]:
        with app.state.playback_lock:
            app.state.active_output = "local"
            app.state.local_player.stop()
            app.state.playback_message = "Stopped"
            return _playback_status(app)

    @app.post("/api/player/local/seek")
    def seek_local_playback(seconds: float) -> dict[str, object]:
        try:
            with app.state.playback_lock:
                app.state.local_player.seek(seconds)
                app.state.playback_message = f"Seeked to {int(max(0, seconds))} seconds"
                return _playback_status(app)
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/next")
    def play_next_local_track() -> dict[str, object]:
        with app.state.playback_lock:
            next_track = app.state.playback_queue.next()
            if next_track is None:
                app.state.local_player.stop()
                app.state.playback_message = "End of queue"
                return _playback_status(app)
            return _play_queue_track(app, next_track)

    @app.post("/api/player/local/previous")
    def play_previous_local_track() -> dict[str, object]:
        with app.state.playback_lock:
            previous_track = app.state.playback_queue.previous()
            if previous_track is None:
                current_track = app.state.playback_queue.current()
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
                except PlayerError as error:
                    raise HTTPException(status_code=503, detail=str(error)) from error
                return _playback_status(app)
            return _play_queue_track(app, previous_track)

    @app.post("/api/player/local/repeat")
    def set_repeat_track(enabled: bool) -> dict[str, object]:
        with app.state.playback_lock:
            app.state.repeat_track = enabled
            app.state.playback_message = (
                "Repeat track on" if app.state.repeat_track else "Repeat track off"
            )
            return _playback_status(app)

    @app.post("/api/player/local/queue/clear")
    def clear_local_queue() -> dict[str, object]:
        with app.state.playback_lock:
            app.state.playback_queue.clear()
            app.state.local_player.stop()
            app.state.playback_message = "Queue cleared"
            return _playback_status(app)

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
            next_current_track, removed_current = app.state.playback_queue.remove(path)
            if removed_current:
                if next_current_track is None:
                    app.state.local_player.stop()
                    app.state.playback_message = "Queue empty"
                    return _playback_status(app)

                if app.state.active_output == "bose":
                    return _play_bose_queue_track(app, next_current_track)

                try:
                    app.state.active_output = "local"
                    _play_track(app, next_current_track)
                    app.state.playback_message = f"Playing {next_current_track.name}"
                except LibraryPathError as error:
                    raise HTTPException(status_code=400, detail=str(error)) from error
                except LibraryNotFoundError as error:
                    raise HTTPException(status_code=404, detail=str(error)) from error
                except UnsupportedAudioFileError as error:
                    raise HTTPException(status_code=415, detail=str(error)) from error
                except PlayerError as error:
                    raise HTTPException(status_code=503, detail=str(error)) from error
            else:
                app.state.playback_message = "Removed track from queue"
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
    def playback_status() -> dict[str, object]:
        with app.state.playback_lock:
            _sync_finished_playback(app)
            return _playback_status(app)

    return app


def _validated_queue_tracks(music_root: Path, queue_paths: list[str]) -> list[QueueTrack]:
    tracks: list[QueueTrack] = []
    for path in queue_paths:
        file_path = resolve_audio_file(music_root, path)
        tracks.append(QueueTrack(path=path, name=file_path.name))
    return tracks


def _play_queue_track(app: FastAPI, track: QueueTrack | None) -> dict[str, object]:
    if track is None:
        app.state.active_output = "local"
        app.state.local_player.stop()
        app.state.playback_message = "End of queue"
        return _playback_status(app)

    try:
        app.state.active_output = "local"
        _play_track(app, track)
        app.state.playback_message = f"Playing {track.name}"
        return _playback_status(app)
    except LibraryPathError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except LibraryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UnsupportedAudioFileError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except PlayerError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _play_bose_queue_track(app: FastAPI, track: QueueTrack) -> dict[str, object]:
    try:
        _play_bose_track(app, track)
        app.state.active_output = "bose"
        app.state.local_player.stop()
        app.state.playback_message = f"Playing on Bose: {track.name}"
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
    app.state.local_player.play(file_path)


def _play_bose_track(app: FastAPI, track: QueueTrack) -> None:
    if app.state.bose_client is None:
        if not app.state.settings.bose_speaker_ip:
            raise BosePlaybackError("bose_speaker_ip is not configured")
        raise BosePlaybackError("aftertouch_base_url is not configured")

    if not app.state.settings.public_base_url:
        raise BosePlaybackError("public_base_url is not configured")

    resolve_audio_file(app.state.settings.music_root, track.path)
    stream_url = build_library_stream_url(app.state.settings.public_base_url, track.path)
    app.state.bose_playback = app.state.bose_client.play_stream(track.name, stream_url)
    app.state.bose_playing = True


def _stop_bose_playback(app: FastAPI) -> None:
    if app.state.bose_client is None:
        raise BosePlaybackError("bose_speaker_ip is not configured")

    app.state.bose_client.stop()
    app.state.bose_playing = False


def _sync_finished_playback(app: FastAPI) -> None:
    if app.state.active_output != "local":
        return

    if not app.state.local_player.consume_finished():
        return

    current_track = app.state.playback_queue.current()
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

    next_track = app.state.playback_queue.next()
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


def _playback_status(app: FastAPI) -> dict[str, object]:
    player_status = _active_player_status(app)
    queue_status = app.state.playback_queue.as_dict()
    current_track = app.state.playback_queue.current()

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
        "now_playing": {
            "path": current_track.path,
            "name": current_track.name,
        }
        if current_track
        else None,
        "queue": queue_status["tracks"],
        "bose": {
            "speaker_ip": app.state.settings.bose_speaker_ip,
            "api_port": app.state.settings.bose_api_port,
            "aftertouch_base_url": app.state.settings.aftertouch_base_url,
            "public_base_url": app.state.settings.public_base_url,
            "stream_url": app.state.bose_playback.stream_url
            if app.state.bose_playback
            else None,
            "playback_url": app.state.bose_playback.playback_url
            if app.state.bose_playback
            else None,
            "command": app.state.bose_playback.command
            if app.state.bose_playback
            else None,
        },
    }


def _active_player_status(app: FastAPI) -> dict[str, object]:
    if app.state.active_output == "bose":
        return {
            "backend": "bose_aftertouch",
            "state": "playing" if app.state.bose_playing else "stopped",
            "process_id": None,
            "elapsed_seconds": None,
            "duration_seconds": None,
            "paused": False,
        }

    return app.state.local_player.status()


app = create_app()
