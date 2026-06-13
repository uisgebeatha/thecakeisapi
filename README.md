# thecakeisapi

thecakeisapi is a lightweight browser-based music player for a Raspberry Pi 4B running Ubuntu.

The first version is intentionally small: FastAPI serves a plain web interface for browsing folders and controlling local Raspberry Pi playback with mpv.

## Requirements

- Python 3.10 or newer
- `mpv` for local Raspberry Pi playback
- A local music folder, defaulting to `/mnt/music`

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

On Linux or Raspberry Pi Ubuntu:

```bash
sudo apt install mpv
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in a browser.

The web interface shows folders and supported audio files from the configured music root. Folder rows can be opened in the browser, file rows include a Play on Pi button, and the bottom playback bar shows shared local playback state for all connected browsers.

## Configuration

The application starts with sensible defaults if no settings file exists:

- `music_root`: `/mnt/music`
- `bose_speaker_ip`: unset
- `mpv_command`: `mpv`
- `mpv_ipc_path`: `/tmp/thecakeisapi-mpv.sock`

For local configuration, copy `config.example.json` to `config.json` and edit it:

```json
{
  "music_root": "/mnt/music",
  "bose_speaker_ip": null,
  "mpv_command": "mpv",
  "mpv_ipc_path": "/tmp/thecakeisapi-mpv.sock"
}
```

`config.json` is ignored by Git so each device can keep its own settings.

The app reads `config.json` from the current working directory by default. To use a different file:

```bash
THECAKEISAPI_CONFIG=/etc/thecakeisapi/config.json uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
```

Individual settings can also be overridden with environment variables:

```bash
THECAKEISAPI_MUSIC_ROOT=/path/to/music uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
```

```bash
THECAKEISAPI_BOSE_SPEAKER_IP=192.168.1.50 uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
```

```bash
THECAKEISAPI_MPV_COMMAND=/usr/bin/mpv uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
```

Configuration is validated when the app starts. The music root, `mpv_command`, and `mpv_ipc_path` must not be empty. `bose_speaker_ip` must be either `null`, omitted, or a valid IP address.

## Current Endpoints

- `GET /` serves the minimal web interface
- `GET /api/health` returns application health
- `GET /api/settings` returns active settings and the loaded config path
- `GET /api/library/status` reports whether the configured music folder exists
- `GET /api/library/browse` lists folders and supported audio files under the configured music root
- `GET /api/library/file` streams a supported audio file from the configured music root
- `POST /api/player/local/play` starts local playback of a supported library file using mpv
- `POST /api/player/local/resume` resumes local mpv playback
- `POST /api/player/local/pause` pauses local mpv playback
- `POST /api/player/local/stop` stops local mpv playback
- `POST /api/player/local/next` plays the next track in the temporary queue
- `POST /api/player/local/previous` plays the previous track in the temporary queue
- `POST /api/player/local/repeat` toggles repeat-track mode
- `GET /api/player/local/status` returns now-playing state, queue, elapsed time, and duration when mpv reports it

To browse the root music folder:

```bash
curl "http://localhost:8000/api/library/browse"
```

To browse a subfolder, pass a relative path:

```bash
curl "http://localhost:8000/api/library/browse?path=Albums"
```

The browse endpoint returns directories and supported audio files only. Supported extensions are currently `.mp3` and `.flac`. Requested paths must stay inside the configured music root; absolute paths and path traversal attempts are rejected.

To stream a supported audio file, pass the relative file path returned by the browse endpoint:

```bash
curl "http://localhost:8000/api/library/file?path=Albums/example.mp3" --output example.mp3
```

Only MP3 and FLAC files are served. The file endpoint uses the same path traversal protection as browsing, returns `audio/mpeg` for MP3 files, and returns `audio/flac` for FLAC files.

To start local playback on the Raspberry Pi, pass the same relative file path:

```bash
curl -X POST "http://localhost:8000/api/player/local/play?path=Albums/example.mp3"
```

The local playback endpoint starts `mpv` on the machine running the FastAPI app. It launches mpv with IPC enabled using `mpv_ipc_path`, and the local playback controls use that IPC socket where possible.

The web UI sends the currently visible audio files as a temporary queue when Play on Pi is clicked. Queue state is kept in memory only and is shared by browsers connected to the same running app process.

When a track finishes, the app advances to the next temporary queue item. If Repeat Track is enabled, it restarts the current track instead. At the end of the queue, playback stops cleanly and reports End of queue.

## Not Implemented Yet

- Persistent playlists
- Bose SoundTouch playback
