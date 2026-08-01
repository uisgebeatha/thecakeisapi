# TheCakeIsAPI

A lightweight self-hosted music player for Raspberry Pi with support for:

* Local playback on a Raspberry Pi using mpv
* Bose SoundTouch playback through AfterTouch
* Browser-based music library navigation
* Queue management
* Track seeking
* Repeat mode
* Automatic track advancement
* NAS / USB SSD music storage

The project is designed to remain simple, low-dependency, and easy to run on Raspberry Pi hardware.

## Dependencies

Required:

- Python virtual environment with the packages in `requirements.txt`
- mpv
- soundtouch-cli v0.120 or later for Bose playback
- AfterTouch v0.120 or later for Bose playback

Recommended:

- ffprobe, supplied by the `ffmpeg` package, for accurate duration detection

## Project Goals

TheCakeIsAPI was created to provide a lightweight browser-based music player that can:

* Browse music stored on local storage
* Play music directly on a Raspberry Pi
* Play music on Bose SoundTouch speakers
* Operate without cloud services
* Integrate with existing AfterTouch installations
* Remain easy to understand and maintain

## Current Architecture

```text
Music Library on USB SSD
        │
        ▼
Raspberry Pi 4
192.168.42.190
        │
        ├── TheCakeIsAPI
        │     ├── Browser UI / API on port 8000
        │     └── Local playback using mpv
        │
        ├── soundtouch-cli
        │
        └── AfterTouch in Docker on port 8001
                    │
                    ▼
          Bose SoundTouch
          192.168.42.101

## Features

### Library

* Folder browsing
* Nested folder support
* MP3 support
* FLAC support
* Hidden system folders filtered automatically

### Queue

* Add To Queue
* Remove Track
* Move Up
* Move Down
* Clear Queue
* Repeat Track

### Playback

#### Raspberry Pi Local

* Play
* Single Pause / Resume control
* Stop
* Next
* Previous
* Seeking
* Progress display

#### Bose SoundTouch

* Play
* Single Pause / Resume control
* Stop
* Next
* Previous
* Queue auto-advance
* Playback progress estimation

Bose controls use `soundtouch-cli`:

* Pause: `soundtouch-cli --host <bose_speaker_ip> play pause`
* Resume / restart: `soundtouch-cli --host <bose_speaker_ip> play start`
* Stop: `soundtouch-cli --host <bose_speaker_ip> play stop`

When Bose playback is paused, the app-side timer and auto-advance countdown pause. Current Bose resume behavior restarts the stream from the beginning, so the app resets the displayed timer on resume/restart instead of showing stale progress.

## Storage

Music is currently stored on:

/mnt/music

Example mount:

/dev/sda1 -> /mnt/music

## Configuration

Configuration file:

config.json

Example:

{
  "music_root": "/mnt/music",
  "bose_speaker_ip": "192.168.42.101",
  "bose_api_port": 8090,
  "aftertouch_base_url": "http://192.168.42.190:8001",
  "public_base_url": "http://192.168.42.190:8000",
  "soundtouch_cli_command": "soundtouch-cli",
  "bose_start_confirm_timeout_seconds": 8.0,
  "bose_start_poll_interval_seconds": 0.5,
  "bose_auto_advance_buffer_seconds": 1.0,
  "mpv_command": "mpv",
  "mpv_ipc_path": "/tmp/thecakeisapi-mpv.sock"
}

`aftertouch_base_url` may point to AfterTouch running on another device, such as a Pi Zero, or locally in Docker on the Pi 4. The Bose speaker must be able to reach the configured address and port.

`soundtouch_cli_command` may be a command available in `PATH`, such as `soundtouch-cli`, or a full executable path.

## Running

Activate virtual environment:

source venv/bin/activate

Start application:

uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000

Access from browser:

http://<pi-address>:8000

## systemd Service

For normal Pi 4 boot startup, run TheCakeIsAPI as a systemd service.

Recommended project path:

/home/controller/thecakeisapi

Recommended virtual environment:

/home/controller/thecakeisapi/venv

Recommended unit file:

```ini
[Unit]
Description=TheCakeIsAPI music player
Wants=network-online.target
After=network-online.target
RequiresMountsFor=/mnt/music

[Service]
Type=simple
User=controller
WorkingDirectory=/home/controller/thecakeisapi
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/controller/thecakeisapi/venv/bin/uvicorn thecakeisapi.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The same template is available at:

deploy/thecakeisapi.service

Create or update the service file on the Pi:

```bash
sudo cp deploy/thecakeisapi.service /etc/systemd/system/thecakeisapi.service
```

Reload systemd:

```bash
sudo systemctl daemon-reload
```

Enable boot startup:

```bash
sudo systemctl enable thecakeisapi.service
```

Start the service:

```bash
sudo systemctl start thecakeisapi.service
```

Check service status:

```bash
systemctl status thecakeisapi.service
```

View logs:

```bash
journalctl -u thecakeisapi.service -f
```

Restart after configuration or code changes:

```bash
sudo systemctl restart thecakeisapi.service
```

Stop the service:

```bash
sudo systemctl stop thecakeisapi.service
```

The service expects `config.json` to exist locally in `/home/controller/thecakeisapi`.
That file should remain uncommitted. The `controller` user must be able to read `/mnt/music`, run `mpv`, and run `soundtouch-cli`.

For accurate track duration detection, install `ffmpeg` so `ffprobe` is available:

```bash
sudo apt install ffmpeg
```

TheCakeIsAPI uses `ffprobe` when available for MP3 and FLAC duration detection. If `ffprobe` is missing or fails, the app falls back to its built-in duration estimator. Accurate duration detection is recommended for Bose playback because Bose queue auto-advance uses the local track duration plus a small buffer.

## Current Status

Implemented
- Pi 4 Local playback
- Bose SoundTouch playback via AfterTouch
- Queue management
- Next / Previous
- Stop
- Pause / Resume (Bose behaviour documented)
- Accurate duration detection using ffprobe
- Automatic queue advance
- Systemd deployment
- AfterTouch v0.120 hosted in Docker on the Pi 4
- soundtouch-cli v0.120 installed on the Pi 4
- SMB music library supported
- Pi 4 local playback verified under systemd
- Bose playback verified under systemd

Current playback engine
The Bose playback engine currently uses:
TheCakeIsAPI → soundtouch-cli → AfterTouch → Bose SoundTouch

## Current Release State

Current development milestone includes:

- systemd-managed TheCakeIsAPI service
- Docker-hosted AfterTouch on the Pi 4
- soundtouch-cli v0.120
- ffprobe-first duration detection
- SMB access to `/mnt/music`

## Future Ideas

* VLC-style interface improvements
* Album artwork
* Search
* Shuffle mode
* Playlist saving
* Multiple Bose speakers
* Optional NAS integration

## License

Personal project.
License to be decided.

## Known Limitations

Bose custom-radio playback does not support true pause/resume.

When paused and restarted, the Bose SoundTouch speaker reconnects to the stream and playback restarts from the beginning.

TheCakeIsAPI therefore treats Bose Resume as Restart and resets the playback timer accordingly.
