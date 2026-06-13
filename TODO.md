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

## Milestone 3 – Queue Management and Seeking

- [x] Add seekable progress bar.
- [x] Allow jumping to any position within the current track.
- [x] Add clear queue button.
- [x] Add visible Add To Queue control.
- [x] Remove track from queue.
- [x] Move queue item up.
- [x] Move queue item down.
- [x] Distinguish Play Track from Play Folder.
- [x] Keep Bose playback out of scope.

## Milestone 4 – Bose Integration

- [x] Configure Bose speaker IP.
- [x] Configure Bose API port.
- [x] Configure AfterTouch base URL.
- [x] Configure Pi 4 public base URL for speaker-fetchable audio links.
- [x] Configure soundtouch-cli command.
- [x] Generate Pi 4 stream URLs from selected library files.
- [x] Send selected tracks to Bose through `soundtouch-cli source custom-radio`.
- [x] Add output selector:
  - [x] Local Pi
  - [x] Bose SoundTouch
- [x] Maintain queue when changing output where practical.
- [ ] Display live Bose playback status from the speaker.
- [ ] Preserve playback position where practical.

## Milestone 5 – NAS Storage

- USB SSD attached to Pi.
- SMB share.
- Music library scanning.
- Automatic rescan.
- Disk usage reporting.

## Minor Improvements

- Hide Windows metadata folders:
  - $RECYCLE.BIN
  - System Volume Information

- Improve VLC-style UI layout.
- Better mobile layout.
- Consider album artwork support.
- Consider volume control.
- Consider shuffle mode.
