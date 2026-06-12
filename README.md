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

The music folder can be changed with:

```bash
THECAKEISAPI_MUSIC_ROOT=/path/to/music uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
```

## Current Endpoints

- `GET /` serves the minimal web interface
- `GET /api/health` returns application health
- `GET /api/settings` returns active settings
- `GET /api/library/status` reports whether the configured music folder exists

## Not Implemented Yet

- Folder browsing
- Queue management
- Local mpv playback
- Bose SoundTouch playback
