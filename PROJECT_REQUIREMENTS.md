# thecakeisapi – Project Requirements

## Goal

Create a browser-based music player for Raspberry Pi 4B running Ubuntu.

The app should manage a local music library stored on directly attached USB storage and allow playback either through the Pi 4B analogue 3.5 mm audio output or through a Bose SoundTouch speaker using AfterTouch / Bose local API control.

## Core Requirements

- Run on Raspberry Pi 4B with Ubuntu.
- Use directly attached USB storage as the music library.
- Provide a VLC-style browser interface.
- Keep the browser interface responsive and practical on phone and desktop screens.
- Browse music by folder and file structure.
- Support MP3 playback.
- Support queue / playlist playback.
- Allow the user to choose output:
  - Pi 4B 3.5 mm audio output.
  - Bose SoundTouch speaker.
- For Bose playback, the speaker should stream the audio file directly from the Pi over the local network.
- Do not rely on Bose cloud services.
- Do not require internet access for normal playback.
- Avoid transcoding unless explicitly added later.
- Keep the system lightweight and suitable for always-on use.

## Suggested Architecture

- Backend: FastAPI
- Frontend: simple HTML/CSS/JavaScript
- Local playback backend: mpv using IPC control
- Bose playback backend: `soundtouch-cli` controlling the Bose local API, with AfterTouch providing custom-radio playback URLs
- Music index: SQLite
- Music root path: configurable, default `/mnt/music`

## First Milestone

Build a minimal proof of concept:

1. List MP3 files from `/mnt/music`.
2. Show them in a browser UI.
3. Play a selected file locally on the Pi using mpv.
4. Expose selected files by HTTP URL.
5. Send a selected file URL to the Bose speaker.


## Design Decisions

- Music browsing will be folder-based only for the first version.
- MP3 support is required.
- FLAC support is nice to have for local Pi playback.
- Bose FLAC support is uncertain and should not be assumed.
- Only one Bose speaker is required initially.
- Bose speaker will use a fixed IP address configured in settings.
- Single-user control is acceptable for the first version.
- Playlists will be temporary queues only for the first version.
- SMB will be used for NAS sharing.
- The app should support switching output between Pi audio and Bose without rebuilding the queue.
- Bose SoundTouch is the default browser playback selection; Pi 4 local playback remains available.
- The UI should distinguish the selected output for new playback from the currently active output.
- While Bose playback is active, periodically synchronize app-side state with the local Bose `/now_playing` endpoint.
- Temporary Bose communication failures must not immediately clear playback state or trigger playback commands.

## Current Deployment Decisions

- TheCakeIsAPI runs as a systemd service on the Pi 4.
- The project Python virtual environment is used in production.
- Music is stored on a USB SSD mounted at `/mnt/music`.
- `/mnt/music` is shared over SMB for Windows and Android LAN access.
- `/mnt/music` should use systemd automount for removable USB storage recovery.
- TheCakeIsAPI must not have a hard `RequiresMountsFor=/mnt/music` dependency on removable USB music storage.
- Temporary loss of the music drive should not make the web application permanently unavailable.
- AfterTouch currently runs in Docker on the Pi 4 at port 8001.
- `soundtouch-cli` is installed directly on the Pi 4.
- AfterTouch location remains configurable so a Pi Zero or another LAN host can also be used.
- The default browser playback output is Bose SoundTouch as of v0.4.0.

## Engineering Note - Bose Pause/Resume

Date: 2026-06-16

Testing performed directly using soundtouch-cli.

Results:
- play pause changes playback state to Stopped.
- play start causes Bose to request the media URL again.
- Bose reconnects to the Pi 4 stream.
- Playback restarts from the beginning.

Evidence:
- Repeated GET requests observed for the same media file after play start.
- Behaviour reproduced outside TheCakeIsAPI using soundtouch-cli.

Conclusion:
- Limitation appears to be in SoundTouch custom-radio / LOCAL_INTERNET_RADIO playback.
- Not caused by TheCakeIsAPI.
- Bose Resume is implemented as Restart.

## Future Engineering Investigation – Native UPnP / DLNA Playback

AfterTouch releases after v0.113 expanded UPnP, DLNA, LOCAL_MUSIC, and STORED_MUSIC support.

A future investigation should determine whether native Bose music-library playback can replace or supplement the current custom-radio method.

The investigation should compare:

- native queue and automatic track advancement
- track duration and position reporting
- pause/resume
- seek
- next/previous
- reliability and startup delay

The current custom-radio backend must remain available until the alternative has been proven.
