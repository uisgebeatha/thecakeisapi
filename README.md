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

Current release: **v0.4.5**.

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

The responsive VLC-style browser keeps the folder library and temporary queue visible side by side on desktop and stacks them cleanly on phone-sized screens. On phones, the app header and current library path remain sticky while directory entries scroll beneath them; the compact Now Playing controls remain fixed at the bottom. Desktop and phone layouts share a single icon-based Previous, Play/Pause, Stop, Next, and Repeat row. Bose SoundTouch is the default choice for new playback; Pi 4 Local remains available in the smaller segmented output switcher. The active output and playback state are shown separately so transport controls remain tied to the backend that is actually playing.

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

While Bose is the active output, TheCakeIsAPI checks the existing Bose `/now_playing` endpoint every five seconds. Confirmed standby, stopped playback, or a source change clears stale app-side playback state without sending a playback command. A brief `INVALID_SOURCE` response during a custom-radio track change is treated as a transition rather than an external takeover. A single communication failure leaves playback state unchanged; three consecutive failures mark the speaker unavailable. Auto-advance is suspended while Bose status is uncertain so an externally powered-off speaker is not restarted by the app-side timer.

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
  "bose_state_poll_interval_seconds": 5.0,
  "bose_auto_advance_buffer_seconds": 1.0,
  "mpv_command": "mpv",
  "mpv_ipc_path": "/tmp/thecakeisapi-mpv.sock"
}

`aftertouch_base_url` may point to AfterTouch running on another device, such as a Pi Zero, or locally in Docker on the Pi 4. The Bose speaker must be able to reach the configured address and port.

`soundtouch_cli_command` may be a command available in `PATH`, such as `soundtouch-cli`, or a full executable path.

Open Settings from the gear button in the application header. The dialog can edit the Bose speaker address, AfterTouch base URL, `soundtouch-cli` command/path, public audio base URL, and Bose status polling interval. Saves use an atomic replacement of `config.json` and preserve every unrelated configuration value.

These settings are consumed when the process starts. Saving never restarts the application automatically. When a saved change requires restart, Settings shows a secondary **Restart TheCakeIsAPI** action with an explicit confirmation that playback will stop briefly. After confirmation, the browser waits for `/api/health` to return and then reloads the settings and component status. A failed or timed-out restart leaves the action available for a manual retry.

The restart API is intentionally narrow: it accepts no command or service name. In the supported systemd deployment it schedules a fixed delayed exit of the current TheCakeIsAPI process, and the existing `Restart=on-failure` policy starts it again. Manual development runs cannot use the action unless they are explicitly managed and enabled.

The read-only Component Status section displays the central TheCakeIsAPI version, the AfterTouch version reported by its `/health` endpoint, and the version reported by `soundtouch-cli --version`. External checks are cached for five minutes and display `Unknown` or `Unavailable` without affecting playback when detection fails.

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

[Service]
Type=simple
User=controller
WorkingDirectory=/home/controller/thecakeisapi
Environment=PYTHONUNBUFFERED=1
Environment=THECAKEISAPI_RESTART_ENABLED=1
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

`THECAKEISAPI_RESTART_ENABLED=1` opts this systemd-managed process into the Settings restart action. No sudoers rule or passwordless `systemctl` permission is required: the app exits only its own process with a fixed failure code, and systemd applies the existing `Restart=on-failure` policy. The endpoint returns a clear unavailable response if the flag is absent or the process is not running under systemd.

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

Do not add a hard `RequiresMountsFor=/mnt/music` dependency to this service. The music library is removable USB storage, and testing showed that systemd will deliberately stop TheCakeIsAPI if the SSD briefly disconnects. The web application should remain available so the library can recover after the drive returns.

Recommended `/etc/fstab` entry for the NTFS USB SSD:

```fstab
UUID=94FC4C08FC4BE2DA /mnt/music ntfs3 defaults,uid=1000,gid=1000,nofail,x-systemd.automount 0 0
```

With `x-systemd.automount`, `mnt-music.automount` remains active and access to `/mnt/music` automatically mounts the SSD when it is present. If the drive is temporarily disconnected, TheCakeIsAPI keeps running; after the SSD is reconnected, browsing the library or Samba access to `/mnt/music` triggers the mount again and normal operation resumes.

For accurate track duration detection, install `ffmpeg` so `ffprobe` is available:

```bash
sudo apt install ffmpeg
```

TheCakeIsAPI uses `ffprobe` when available for MP3 and FLAC duration detection. If `ffprobe` is missing or fails, FLAC duration comes from STREAMINFO and MP3 duration is calculated by scanning audio frames, including variable-bitrate files. Accurate duration detection is recommended for Bose playback because Bose queue auto-advance uses the local track duration plus a small buffer.

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
