from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
    queue_paths: list[str] = []


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
    app.state.playback_queue = PlaybackQueue()

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
    def read_settings() -> dict[str, str | None]:
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
            queue_tracks = _validated_queue_tracks(
                app_settings.music_root,
                request.queue_paths if request else [],
            )
            selected_track = app.state.playback_queue.set_tracks(queue_tracks, path)
            file_path = resolve_audio_file(app_settings.music_root, selected_track.path)
            app.state.local_player.play(file_path)
            return _playback_status(app)
        except LibraryPathError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LibraryNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except UnsupportedAudioFileError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/resume")
    def resume_local_playback() -> dict[str, object]:
        try:
            current_track = app.state.playback_queue.current()
            if app.state.local_player.status()["state"] == "stopped":
                if current_track is None:
                    raise HTTPException(status_code=404, detail="No track is selected")
                file_path = resolve_audio_file(app_settings.music_root, current_track.path)
                app.state.local_player.play(file_path)
            else:
                app.state.local_player.resume()
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
            app.state.local_player.pause()
            return _playback_status(app)
        except PlayerError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/player/local/stop")
    def stop_local_playback() -> dict[str, object]:
        app.state.local_player.stop()
        return _playback_status(app)

    @app.post("/api/player/local/next")
    def play_next_local_track() -> dict[str, object]:
        return _play_queue_track(app, app.state.playback_queue.next())

    @app.post("/api/player/local/previous")
    def play_previous_local_track() -> dict[str, object]:
        return _play_queue_track(app, app.state.playback_queue.previous())

    @app.get("/api/player/local/status")
    def local_playback_status() -> dict[str, object]:
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
        raise HTTPException(status_code=404, detail="No track is available")

    try:
        file_path = resolve_audio_file(app.state.settings.music_root, track.path)
        app.state.local_player.play(file_path)
        return _playback_status(app)
    except LibraryPathError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except LibraryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UnsupportedAudioFileError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except PlayerError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _playback_status(app: FastAPI) -> dict[str, object]:
    player_status = app.state.local_player.status()
    queue_status = app.state.playback_queue.as_dict()
    current_track = app.state.playback_queue.current()

    return {
        "backend": player_status["backend"],
        "state": player_status["state"],
        "process_id": player_status["process_id"],
        "elapsed_seconds": player_status["elapsed_seconds"],
        "duration_seconds": player_status["duration_seconds"],
        "paused": player_status["paused"],
        "now_playing": {
            "path": current_track.path,
            "name": current_track.name,
        }
        if current_track
        else None,
        "queue": queue_status["tracks"],
    }


app = create_app()
