# thecakeisapi

thecakeisapi is a lightweight browser-based music player for a Raspberry Pi 4B running Ubuntu.

The first version is intentionally small: FastAPI serves a plain web interface and exposes basic health and library status endpoints. Music playback is not implemented yet.

## Requirements

- Python 3.10 or newer
- A local music folder, defaulting to `/mnt/music`

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

On Linux or Raspberry Pi Ubuntu:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in a browser.

## Configuration

The application starts with sensible defaults if no settings file exists:

- `music_root`: `/mnt/music`
- `bose_speaker_ip`: unset

For local configuration, copy `config.example.json` to `config.json` and edit it:

```json
{
  "music_root": "/mnt/music",
  "bose_speaker_ip": null
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

Configuration is validated when the app starts. The music root must not be empty, and `bose_speaker_ip` must be either `null`, omitted, or a valid IP address.

## Current Endpoints

- `GET /` serves the minimal web interface
- `GET /api/health` returns application health
- `GET /api/settings` returns active settings and the loaded config path
- `GET /api/library/status` reports whether the configured music folder exists

## Not Implemented Yet

- Folder browsing
- Queue management
- Local mpv playback
- Bose SoundTouch playback
