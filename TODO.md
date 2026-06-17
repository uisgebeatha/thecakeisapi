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
- [x] Stop Bose playback with `soundtouch-cli play stop`.
- [x] Pause Bose playback with `soundtouch-cli play pause`.
- [x] Resume Bose playback with `soundtouch-cli play start`.
- [x] Pause Bose app-side timer and auto-advance countdown while paused.
- [x] Reset Bose app-side timer on resume when position continuity cannot be verified.
- [x] Treat Bose resume as restart until true resume support is discovered.
- [x] Poll Bose `/now_playing` after starting Bose playback.
- [x] Track Bose app-side playback state and elapsed time.
- [x] Estimate Bose queue auto-advance from local duration plus buffer.
- [x] Use `ffprobe` when available for accurate MP3/FLAC duration detection.
- [x] Respect Repeat Track for Bose estimated auto-advance.
- [x] Add output selector:
  - [x] Local Pi
  - [x] Bose SoundTouch
- [x] Maintain queue when changing output where practical.
- [x] Display Bose app-side playback/timer status.
- [ ] Display live Bose playback status from the speaker beyond start confirmation.
- [ ] Preserve playback position where practical.

## Playback State Cleanup and Library Polish

- [x] Preserve Bose playback UI state after browser refresh through backend status.
- [x] Keep Bose Stop available after browser refresh while Bose playback is active.
- [x] Use a single Pause/Resume button for Pi 4 local playback.
- [x] Keep Pause/Resume button state consistent after browser refresh.
- [x] Keep queue available after Bose Stop.
- [x] Stop Pi 4 local mpv playback before starting Bose playback.
- [x] Stop Bose playback before starting Pi 4 local playback.
- [x] Lower default Bose auto-advance buffer to 1 second.
- [x] Hide common filesystem metadata folders from library browsing.
- [ ] Detect external Bose state changes or power-off using periodic `now_playing` polling.

## Milestone 5 Deployment

- [x] Add recommended systemd service template for TheCakeIsAPI.
- [x] Document boot startup with `systemctl enable`.
- [x] Document automatic restart on service failure.
- [x] Document service management commands.
- [x] Document `ffmpeg` / `ffprobe` recommendation for accurate Bose auto-advance timing.
- [ ] Verify mpv local playback works under systemd.
- [ ] Verify Bose playback works under systemd.


## Milestone 6 – NAS Storage

- USB SSD attached to Pi.
- SMB share.
- Music library scanning.
- Automatic rescan.
- Disk usage reporting.

## Minor Improvements

- Improve VLC-style UI layout.
- Better mobile layout.
- Consider album artwork support.
- Consider volume control.
- Consider shuffle mode.

Improve output switching UX:
- Current selector may jump back to the active output.
- This is technically correct but visually confusing.
- Consider replacing selector with explicit “Play on Pi 4” / “Play on Bose” actions or an “active output” display.

## Design Investigation

Future Investigation:
- Evaluate DLNA/UPnP playback path for Bose SoundTouch.
- Determine whether DLNA playback supports true pause/resume and seek.
- Compare DLNA behaviour against current custom-radio implementation.

## Configuration Improvements

- Make AfterTouch service location clearly configurable.
  - Support Pi Zero AfterTouch.
  - Support Pi 4 Docker AfterTouch.
  - Document required `aftertouch_base_url` behavior.
  - Note that the Bose speaker must be able to reach/resolve this URL.

- Make `soundtouch-cli` location/command clearly configurable.
  - Support system-installed `soundtouch-cli`.
  - Support custom path if needed.
  - Document `soundtouch_cli_command` in README.
