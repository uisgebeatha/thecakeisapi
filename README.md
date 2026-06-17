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

## Project Goals

TheCakeIsAPI was created to provide a lightweight browser-based music player that can:

* Browse music stored on local storage
* Play music directly on a Raspberry Pi
* Play music on Bose SoundTouch speakers
* Operate without cloud services
* Integrate with existing AfterTouch installations
* Remain easy to understand and maintain

## Current Architecture

Music Library
      │
      ▼
 Raspberry Pi 4
 (thecakeisapi)
      │
      ├── Local Playback (mpv)
      │
      └── Bose Playback
              │
              ▼
       AfterTouch
     Raspberry Pi Zero
              │
              ▼
      Bose SoundTouch

Current network configuration:

Pi 4 (thecakeisapi)
192.168.42.190

Pi Zero (AfterTouch)
192.168.42.102

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
  "aftertouch_base_url": "http://192.168.42.102",
  "public_base_url": "http://192.168.42.190:8000",
  "soundtouch_cli_command": "soundtouch-cli",
  "mpv_command": "mpv",
  "mpv_ipc_path": "/tmp/thecakeisapi-mpv.sock"
}

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

Working:

* Library browsing
* Queue management
* Local playback
* Bose playback
* Bose pause/resume
* Auto-advance
* Repeat mode
* USB SSD music library

In Progress:

* UI improvements
* Output switching workflow
* Bose playback state refinement

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
