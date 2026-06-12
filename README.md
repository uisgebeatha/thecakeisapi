# thecakeisapi

thecakeisapi is a lightweight browser-based music player for a Raspberry Pi 4B running Ubuntu.

The first version is intentionally small: FastAPI serves a plain web interface for browsing folders and exposes basic library endpoints. Music playback is not implemented yet.

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

The web interface shows folders and supported audio files from the configured music root. Folder rows can be opened in the browser; file rows are display-only until playback is added.

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

The local playback endpoint starts `mpv` on the machine running the FastAPI app. It launches mpv with IPC enabled using `mpv_ipc_path`, but playback controls are not exposed yet.

## Not Implemented Yet

- Queue management
- Local playback controls
- Bose SoundTouch playback
