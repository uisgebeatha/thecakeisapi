# thecakeisapi

thecakeisapi is a lightweight browser-based music player for a Raspberry Pi 4B running Ubuntu.

The first version is intentionally small: FastAPI serves a plain web interface for browsing folders, controlling local Raspberry Pi playback with mpv, and handing Pi-hosted stream URLs to a Bose SoundTouch speaker through AfterTouch.

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

The web interface shows folders and supported audio files from the configured music root. Folder rows can be opened in the browser, folders can be queued with Play Folder, individual files can be started with Play Track or appended with Add To Queue, and the bottom playback bar shows shared local playback state for all connected browsers.

## Configuration

The application starts with sensible defaults if no settings file exists:

- `music_root`: `/mnt/music`
- `bose_speaker_ip`: unset
- `bose_api_port`: `8090`
- `aftertouch_base_url`: unset
- `public_base_url`: unset
- `soundtouch_cli_command`: `soundtouch-cli`
- `bose_start_confirm_timeout_seconds`: `8.0`
- `bose_start_poll_interval_seconds`: `0.5`
- `bose_auto_advance_buffer_seconds`: `1.0`
- `mpv_command`: `mpv`
- `mpv_ipc_path`: `/tmp/thecakeisapi-mpv.sock`

For local configuration, copy `config.example.json` to `config.json` and edit it:

```json
{
  "music_root": "/mnt/music",
  "bose_speaker_ip": "192.168.42.101",
  "bose_api_port": 8090,
  "aftertouch_base_url": "http://192.168.42.102",
  "public_base_url": "http://192.168.42.100:8000",
  "soundtouch_cli_command": "soundtouch-cli",
  "bose_start_confirm_timeout_seconds": 8.0,
  "bose_start_poll_interval_seconds": 0.5,
  "bose_auto_advance_buffer_seconds": 1.0,
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
THECAKEISAPI_AFTERTOUCH_BASE_URL=http://192.168.42.102 uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
```

```bash
THECAKEISAPI_PUBLIC_BASE_URL=http://192.168.42.100:8000 uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
```

```bash
THECAKEISAPI_SOUNDTOUCH_CLI_COMMAND=/usr/local/bin/soundtouch-cli uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
```

```bash
THECAKEISAPI_MPV_COMMAND=/usr/bin/mpv uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
```

Configuration is validated when the app starts. The music root, `mpv_command`, `mpv_ipc_path`, and `soundtouch_cli_command` must not be empty. `bose_speaker_ip` must be either `null`, omitted, or a valid IP address. `bose_api_port` must be between `1` and `65535`. `aftertouch_base_url` and `public_base_url` must be HTTP or HTTPS URLs when set. Bose timing values must be non-negative, and `bose_start_poll_interval_seconds` must be greater than `0`.

For Bose playback, `public_base_url` must be the Pi 4 URL that the Bose speaker can fetch on the local network. Do not use `localhost` for this setting. The intended audio path is:

```text
Bose SoundTouch -> Pi 4 /api/library/file endpoint
```

AfterTouch can run on another machine, such as a Pi Zero. Configure its base URL with `aftertouch_base_url`. Bose playback uses the same flow as the working manual command:

```bash
soundtouch-cli --host 192.168.42.101 source custom-radio --service-url "http://bose-controller.local" --name "Track Name" --url "<Pi 4 stream URL>"
```

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
- `POST /api/player/local/seek` jumps to a position in the current track
- `POST /api/player/local/next` plays the next track in the temporary queue
- `POST /api/player/local/previous` plays the previous track in the temporary queue
- `POST /api/player/local/repeat` toggles repeat-track mode
- `POST /api/player/local/queue/add` appends tracks to the temporary queue
- `POST /api/player/local/queue/clear` clears the temporary queue and stops playback
- `POST /api/player/local/queue/remove` removes a track from the temporary queue
- `POST /api/player/local/queue/move-up` moves a queued track up
- `POST /api/player/local/queue/move-down` moves a queued track down
- `GET /api/player/local/status` returns now-playing state, queue, elapsed time, and duration when mpv reports it
- `GET /api/player/status` returns the active playback status for the selected output
- `POST /api/player/bose/play` sends a supported library file to Bose through `soundtouch-cli source custom-radio`
- `POST /api/player/bose/resume` resends the current queue item to Bose
- `POST /api/player/bose/next` sends the next queue item to Bose
- `POST /api/player/bose/previous` sends the previous queue item to Bose
- `POST /api/player/bose/stop` stops Bose playback with `soundtouch-cli play stop`

To browse the root music folder:

```bash
curl "http://localhost:8000/api/library/browse"
```

To browse a subfolder, pass a relative path:

```bash
curl "http://localhost:8000/api/library/browse?path=Albums"
```

The browse endpoint returns directories and supported audio files only. Supported extensions are currently `.mp3` and `.flac`. Requested paths must stay inside the configured music root; absolute paths and path traversal attempts are rejected.

The browser hides common storage metadata folders such as `$RECYCLE.BIN`, `System Volume Information`, `.Trashes`, `.Spotlight-V100`, `.fseventsd`, and `lost+found`.

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

The web UI keeps queue state in memory only and shares it across browsers connected to the same running app process. Play Track queues only the selected file. Add To Queue appends an individual file without starting playback. Play Folder queues supported files directly inside that folder. Queue rows can be moved up, moved down, or removed, and the queue can be cleared.

When a track finishes, the app advances to the next temporary queue item. If Repeat Track is enabled, it restarts the current track instead. At the end of the queue, playback stops cleanly and reports End of queue.

The playback position slider seeks within the current track when mpv reports a duration.

To start Bose playback, configure `aftertouch_base_url` and `public_base_url`, then pass the same relative file path:

```bash
curl -X POST "http://localhost:8000/api/player/bose/play?path=Albums/example.mp3"
```

The Bose endpoint resolves the library path with the same traversal protection as local playback, builds a Pi 4 stream URL such as:

```text
http://192.168.42.100:8000/api/library/file?path=Albums%2Fexample.mp3
```

Then it runs `soundtouch-cli` using the custom-radio flow:

```bash
soundtouch-cli --host 192.168.42.101 source custom-radio --service-url "http://192.168.42.102" --name "example.mp3" --url "http://192.168.42.100:8000/api/library/file?path=Albums%2Fexample.mp3"
```

When this works, the Pi 4 FastAPI logs should show the Bose speaker requesting `/api/library/file`. This confirms the audio is not being proxied through the Pi Zero.

Bose Stop runs `soundtouch-cli --host <bose_speaker_ip> play stop`. It does not power off the speaker or switch sources. Bose Pause and seek are not enabled yet.

After a Bose play command is sent, the app polls `http://<bose_speaker_ip>:<bose_api_port>/now_playing` for a short confirmation window. The Bose app-side timer starts only after the speaker appears to have switched to a custom/local internet radio source. If confirmation times out, status reports a warning instead of pretending playback is fully confirmed.

When local duration can be determined from the audio file, the Bose timer counts up in the UI and the app estimates end-of-track using `duration + bose_auto_advance_buffer_seconds`. It then advances the shared queue, or replays the same track when Repeat Track is enabled. If duration is unknown, elapsed time may be shown after confirmation, but automatic advance is disabled.

Only one output should be active at a time. Starting Bose playback stops local mpv playback first, and starting local Pi playback stops active Bose playback first.

## Not Implemented Yet

- Persistent playlists
- Bose pause and seek
