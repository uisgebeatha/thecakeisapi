import os
from collections.abc import Callable
from threading import Lock, Timer


RESTART_ENABLED_ENVIRONMENT_VARIABLE = "THECAKEISAPI_RESTART_ENABLED"
RESTART_EXIT_CODE = 75
RESTART_DELAY_SECONDS = 1.0


class RestartUnavailableError(RuntimeError):
    """Raised when this process cannot safely request a managed restart."""


class RestartAlreadyScheduledError(RuntimeError):
    """Raised when a restart has already been requested."""


class ApplicationRestarter:
    def __init__(
        self,
        *,
        enabled: bool,
        systemd_managed: bool,
        delay_seconds: float = RESTART_DELAY_SECONDS,
        timer_factory: Callable[..., Timer] = Timer,
        exit_process: Callable[[int], None] = os._exit,
    ) -> None:
        self.enabled = enabled
        self.systemd_managed = systemd_managed
        self.delay_seconds = delay_seconds
        self._timer_factory = timer_factory
        self._exit_process = exit_process
        self._lock = Lock()
        self._restart_scheduled = False

    @classmethod
    def from_environment(cls) -> "ApplicationRestarter":
        enabled_value = os.getenv(RESTART_ENABLED_ENVIRONMENT_VARIABLE, "")
        return cls(
            enabled=enabled_value.strip().lower() in {"1", "true", "yes"},
            systemd_managed=bool(os.getenv("INVOCATION_ID")),
        )

    def request_restart(self) -> None:
        if not self.enabled:
            raise RestartUnavailableError(
                "Application restart is not enabled for this process",
            )
        if not self.systemd_managed:
            raise RestartUnavailableError(
                "Application restart is available only when running under systemd",
            )

        with self._lock:
            if self._restart_scheduled:
                raise RestartAlreadyScheduledError(
                    "TheCakeIsAPI restart is already in progress",
                )
            self._restart_scheduled = True

            try:
                restart_timer = self._timer_factory(
                    self.delay_seconds,
                    self._exit_process,
                    args=(RESTART_EXIT_CODE,),
                )
                restart_timer.daemon = True
                restart_timer.start()
            except Exception as error:
                self._restart_scheduled = False
                raise RestartUnavailableError(
                    f"Could not schedule TheCakeIsAPI restart: {error}",
                ) from error
