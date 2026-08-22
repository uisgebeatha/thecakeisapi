# AGENTS.md

## Project Overview

thecakeisapi is a lightweight browser-based music player designed for Raspberry Pi 4B running Ubuntu.

The application manages a local music library stored on directly attached USB storage and supports playback through either:

* Raspberry Pi analogue 3.5mm audio output
* Bose SoundTouch speaker using AfterTouch and the Bose local API

The application should be suitable for long-term unattended operation on low-power hardware.

Refer to PROJECT_REQUIREMENTS.md for functional requirements.

---

## Development Principles

* Keep solutions simple.
* Prefer proven libraries over custom implementations.
* Avoid unnecessary dependencies.
* Avoid cloud services.
* Avoid internet dependencies for normal operation.
* Prioritise reliability over feature count.
* Prioritise maintainability over cleverness.

---

## Architecture Guidelines

Use modular design.

Suggested modules:

* library
* playlist
* player
* bose
* webui
* settings

Modules should be loosely coupled and easily testable.

---

## Performance Goals

Target hardware:

* Raspberry Pi 4B
* 4GB RAM

The application should:

* Start quickly
* Run continuously
* Use minimal CPU when idle
* Use minimal memory
* Avoid unnecessary background processing

---

## User Interface

The interface should be inspired by VLC file browsing.

Priorities:

1. Fast
2. Simple
3. Mobile friendly
4. Folder-based navigation

Avoid unnecessary visual complexity.

---

## Music Library

Initial version:

* Folder browsing only
* No mandatory metadata scanning
* No artist database
* No album database

The filesystem is the source of truth.

---

## Audio Output

Support:

1. Local playback using mpv
2. Bose playback using Bose local API

The queue must remain independent from the output backend.

Future output backends may be added later.

---

## Bose Integration

Assume:

* Single Bose speaker
* Fixed speaker IP address
* Local network operation
* AfterTouch location and port are configurable
* `soundtouch-cli` location is configurable
* Current production deployment uses AfterTouch in Docker on the Pi 4

Do not depend on Bose cloud services.

Keep custom-radio playback as the stable Bose backend until any UPnP/DLNA replacement has been tested independently.

---

---

## Storage

Use SQLite where persistence is required.

Do not introduce heavier database systems.

---

## Documentation

When making significant changes:

* Update README.md
* Update TODO.md if appropriate
* Document setup steps clearly

---

## Coding Style

* Prefer readability over brevity.
* Use descriptive names.
* Keep functions small.
* Add comments only where useful.
* Avoid premature optimisation.
* Avoid unnecessary abstraction.
* Prefer standard Python tooling.

---

## Deployment and Upgrade Instructions

When providing deployment or upgrade instructions:

* Verify release asset names, URLs, checksums, and the installation method before presenting commands.
* Base commands on the user's actual installation rather than a generic deployment.
* Prefer one complete, verified procedure over iterative trial-and-error instructions.
* Do not reintroduce a hard systemd dependency requiring `/mnt/music` to remain continuously mounted.
* Preserve removable-storage recovery behavior when changing deployment configuration.
