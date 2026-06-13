import json
import socket
import subprocess
import time
from pathlib import Path
from threading import Lock
from typing import Any


class PlayerError(Exception):
    """Raised when local playback cannot be controlled."""


class MpvPlayer:
    def __init__(self, mpv_command: str, ipc_path: Path) -> None:
        self.mpv_command = mpv_command
        self.ipc_path = ipc_path
        self._process: subprocess.Popen[bytes] | None = None
        self._current_path: Path | None = None
        self._started_at: float | None = None
        self._paused = False
        self._lock = Lock()

    def play(self, audio_path: Path) -> dict[str, object]:
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

            self._current_path = audio_path
            self._started_at = time.monotonic()
            self._paused = False
            return self.status()

    def pause(self) -> dict[str, object]:
        with self._lock:
            self._require_running()
            self._send_command(["set_property", "pause", True])
            self._paused = True
            return self.status()

    def resume(self) -> dict[str, object]:
        with self._lock:
            self._require_running()
            self._send_command(["set_property", "pause", False])
            self._paused = False
            return self.status()

    def stop(self) -> dict[str, object]:
        if self._process is not None and self._process.poll() is None:
            try:
                self._send_command(["stop"])
            except PlayerError:
                pass

            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)

        self._process = None
        self._current_path = None
        self._started_at = None
        self._paused = False
        return self.status()

    def consume_finished(self) -> bool:
        with self._lock:
            if self._process is None:
                return False

            if self._process.poll() is None:
                return False

            self._process = None
            self._current_path = None
            self._started_at = None
            self._paused = False
            return True

    def status(self) -> dict[str, object]:
        process_id = None
        if self._process is not None and self._process.poll() is None:
            process_id = self._process.pid

        if process_id is None:
            return {
                "backend": "mpv",
                "state": "stopped",
                "process_id": None,
                "path": None,
                "ipc_path": str(self.ipc_path),
                "elapsed_seconds": None,
                "duration_seconds": None,
                "paused": False,
            }

        elapsed_seconds = self._read_property("time-pos")
        duration_seconds = self._read_property("duration")
        paused = self._read_property("pause")
        if isinstance(paused, bool):
            self._paused = paused

        if elapsed_seconds is None and self._started_at is not None and not self._paused:
            elapsed_seconds = max(0.0, time.monotonic() - self._started_at)

        return {
            "backend": "mpv",
            "state": "paused" if self._paused else "playing",
            "process_id": process_id,
            "path": str(self._current_path) if self._current_path else None,
            "ipc_path": str(self.ipc_path),
            "elapsed_seconds": elapsed_seconds,
            "duration_seconds": duration_seconds,
            "paused": self._paused,
        }

    def _build_command(self, audio_path: Path) -> list[str]:
        return [
            self.mpv_command,
            "--no-terminal",
            "--force-window=no",
            f"--input-ipc-server={self.ipc_path}",
            str(audio_path),
        ]

    def _require_running(self) -> None:
        if self._process is None or self._process.poll() is not None:
            raise PlayerError("mpv is not currently running")

    def _read_property(self, property_name: str) -> Any:
        try:
            response = self._send_command(["get_property", property_name])
        except PlayerError:
            return None

        if response.get("error") != "success":
            return None

        return response.get("data")

    def _send_command(self, command: list[Any]) -> dict[str, Any]:
        if not hasattr(socket, "AF_UNIX"):
            raise PlayerError("mpv IPC requires Unix domain socket support")

        request = json.dumps({"command": command}).encode("utf-8") + b"\n"

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as ipc_socket:
                ipc_socket.settimeout(0.5)
                ipc_socket.connect(str(self.ipc_path))
                ipc_socket.sendall(request)
                response = ipc_socket.recv(4096)
        except OSError as error:
            raise PlayerError(f"mpv IPC is not available: {error}") from error

        try:
            return json.loads(response.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise PlayerError("mpv IPC returned invalid JSON") from error
