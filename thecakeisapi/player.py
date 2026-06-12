import subprocess
from pathlib import Path
from threading import Lock


class PlayerError(Exception):
    """Raised when local playback cannot be started."""


class MpvPlayer:
    def __init__(self, mpv_command: str, ipc_path: Path) -> None:
        self.mpv_command = mpv_command
        self.ipc_path = ipc_path
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = Lock()

    def play(self, audio_path: Path) -> dict[str, str | int | None]:
        with self._lock:
            self.stop()
            command = self._build_command(audio_path)

            try:
                self._process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError as error:
                raise PlayerError(f"mpv command not found: {self.mpv_command}") from error
            except OSError as error:
                raise PlayerError(f"mpv could not be started: {error}") from error

            return self.status(audio_path)

    def stop(self) -> None:
        if self._process is None:
            return

        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)

        self._process = None

    def status(self, audio_path: Path | None = None) -> dict[str, str | int | None]:
        process_id = None
        if self._process is not None and self._process.poll() is None:
            process_id = self._process.pid

        return {
            "backend": "mpv",
            "status": "playing" if process_id else "stopped",
            "process_id": process_id,
            "path": str(audio_path) if audio_path else None,
            "ipc_path": str(self.ipc_path),
        }

    def _build_command(self, audio_path: Path) -> list[str]:
        return [
            self.mpv_command,
            "--no-terminal",
            "--force-window=no",
            f"--input-ipc-server={self.ipc_path}",
            str(audio_path),
        ]
