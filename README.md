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
* Resume: `soundtouch-cli --host <bose_speaker_ip> play start`
* Stop: `soundtouch-cli --host <bose_speaker_ip> play stop`

When Bose playback is paused, the app-side timer and auto-advance countdown pause. If Bose resume position cannot be verified, the app resets the displayed timer on resume instead of showing an untrusted elapsed position.

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
