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
- [x] Configure `/mnt/music` with systemd automount for removable USB SSD recovery.
- [x] Keep TheCakeIsAPI active during temporary USB music-storage loss.
- [x] Verify recovery after SSD reconnect through automount access.
- [x] Document `ffmpeg` / `ffprobe` recommendation for accurate Bose auto-advance timing.
- [x] Verify mpv local playback works under systemd.
- [x] Verify Bose playback works under systemd.


## Milestone 6 – NAS Storage

- [x] Attach USB SSD to Pi 4.
- [x] Mount music storage at `/mnt/music`.
- [x] Create SMB share for Windows and Android LAN access.
- [ ] Document SMB installation, permissions, and client connection.
- [ ] Add disk usage reporting.
- [ ] Decide whether music library scanning is needed.
- [ ] Decide whether automatic rescan is needed.

## v0.4.0 - UI / UX

- [x] Make Bose SoundTouch the default playback output.
- [x] Improve the responsive VLC-style layout for phone and desktop browsers.
- [x] Clean up spacing, alignment, hierarchy, and control styling without adding frontend dependencies.
- [x] Replace the output dropdown with a clear Bose / Pi 4 Local choice.
- [x] Show the active output separately and keep transport controls tied to it.
- [x] Display the application version in the top-right of the UI.

## Minor Improvements

- [ ] Consider album artwork support.
- [ ] Consider volume control.
- [ ] Consider shuffle mode.

## Design Investigation

### Native Bose UPnP / DLNA Playback

- [ ] Review AfterTouch v0.116–v0.120 UPnP and STORED_MUSIC support.
- [ ] Set up a test DLNA server using the existing `/mnt/music` library.
- [ ] Test native Bose queue handling.
- [ ] Test automatic next-track playback.
- [ ] Test pause/resume behaviour.
- [ ] Test seek and track-position reporting.
- [ ] Compare startup delay and reliability with custom-radio playback.
- [ ] Keep the current custom-radio backend available during evaluation.

## Configuration Improvements

- [x] Make AfterTouch service location configurable through `aftertouch_base_url`.
  - [x] Support Pi Zero AfterTouch.
  - [x] Support Pi 4 Docker AfterTouch.
  - [ ] Fully document address, port, and Bose reachability requirements.

- [x] Make `soundtouch-cli` command/location configurable through `soundtouch_cli_command`.
  - [x] Support a system-installed command.
  - [x] Support a full custom executable path.
  - [ ] Fully document configuration examples.

- [ ] Consider a future settings UI for editing these values.
- [ ] Display TheCakeIsAPI, AfterTouch, and `soundtouch-cli` versions in the UI.
