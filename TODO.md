# TODO

## Milestone 1

- [x] Create FastAPI application
- [x] Create settings file support
- [x] Create web interface
- [x] Browse folders under configured music path
- [x] Display files and folders
- [x] Play MP3 locally using mpv

## Playback Preparation

- [x] Serve supported audio files from the configured music library
- [x] Add local mpv playback backend and start endpoint
- [x] Add Play on Pi button to the web interface

## Milestone 2 – Playback Controls and VLC-style UI

- [x] Add local playback controls:
  - [x] Play
  - [x] Pause
  - [x] Stop
  - [x] Next track
  - [x] Previous track
- [x] Add now-playing display.
- [x] Add track timer:
  - [x] Show elapsed time.
  - [x] Show total track duration where available.
  - [x] Timer should count up during playback.
- [x] Add basic playlist/queue display.
- [x] UI layout should be inspired by VLC:
  - [x] Playlist/file list area.
  - [x] Now-playing area.
  - [x] Bottom playback control bar.
- [x] Playback state should be visible when opening the app from another browser/device.

## Playback Reliability and Controls

- [x] Add repeat track option.
- [x] Add repeat mode state to playback status.
- [x] Add UI control to toggle repeat track on/off.
- [x] Automatically advance to the next track when the current track finishes.
- [x] Replay the same track when repeat track is enabled.
- [x] Stop cleanly when the last track finishes and repeat track is off.
- [x] Handle Next on the last track without an error.
- [x] Handle Previous on the first track without an error.
- [x] Keep Bose playback out of scope.

## Milestone 3 – Bose Integration

- Configure Bose speaker IP.
- Send selected tracks to Bose.
- Display Bose playback status.
- Switch output between:
  - Local Pi
  - Bose SoundTouch
- Maintain queue when changing output.
- Preserve playback position where practical.

## Milestone 4 – NAS Storage

- USB SSD attached to Pi.
- SMB share.
- Music library scanning.
- Automatic rescan.
- Disk usage reporting.
