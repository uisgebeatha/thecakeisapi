import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException
from pydantic import ValidationError

from thecakeisapi.main import RestartRequest
from thecakeisapi.restart import (
    ApplicationRestarter,
    RESTART_EXIT_CODE,
    RestartAlreadyScheduledError,
    RestartUnavailableError,
)
from tests.test_configuration import route_endpoint, temporary_settings_app


SERVICE_UNIT = Path(__file__).resolve().parents[1] / "deploy" / "thecakeisapi.service"


class FakeTimer:
    def __init__(self, interval, function, args=(), fail_to_start=False) -> None:
        self.interval = interval
        self.function = function
        self.args = args
        self.fail_to_start = fail_to_start
        self.daemon = False
        self.started = False

    def start(self) -> None:
        if self.fail_to_start:
            raise RuntimeError("timer unavailable")
        self.started = True

    def run(self) -> None:
        self.function(*self.args)


class FakeTimerFactory:
    def __init__(self, fail_to_start=False) -> None:
        self.fail_to_start = fail_to_start
        self.timers = []

    def __call__(self, interval, function, args=()) -> FakeTimer:
        timer = FakeTimer(interval, function, args, self.fail_to_start)
        self.timers.append(timer)
        return timer


class ApplicationRestarterTests(unittest.TestCase):
    def test_restart_exits_only_the_current_process_with_fixed_code(self) -> None:
        timer_factory = FakeTimerFactory()
        exit_process = Mock()
        restarter = ApplicationRestarter(
            enabled=True,
            systemd_managed=True,
            timer_factory=timer_factory,
            exit_process=exit_process,
        )

        restarter.request_restart()

        self.assertEqual(len(timer_factory.timers), 1)
        self.assertTrue(timer_factory.timers[0].started)
        self.assertTrue(timer_factory.timers[0].daemon)
        exit_process.assert_not_called()

        timer_factory.timers[0].run()
        exit_process.assert_called_once_with(RESTART_EXIT_CODE)

    def test_restart_is_unavailable_without_explicit_enablement(self) -> None:
        restarter = ApplicationRestarter(enabled=False, systemd_managed=True)

        with self.assertRaisesRegex(RestartUnavailableError, "not enabled"):
            restarter.request_restart()

    def test_restart_is_unavailable_outside_systemd(self) -> None:
        restarter = ApplicationRestarter(enabled=True, systemd_managed=False)

        with self.assertRaisesRegex(RestartUnavailableError, "under systemd"):
            restarter.request_restart()

    def test_repeated_restart_request_is_rejected(self) -> None:
        restarter = ApplicationRestarter(
            enabled=True,
            systemd_managed=True,
            timer_factory=FakeTimerFactory(),
        )
        restarter.request_restart()

        with self.assertRaises(RestartAlreadyScheduledError):
            restarter.request_restart()

    def test_timer_failure_returns_useful_error_and_allows_retry(self) -> None:
        restarter = ApplicationRestarter(
            enabled=True,
            systemd_managed=True,
            timer_factory=FakeTimerFactory(fail_to_start=True),
        )

        for _attempt in range(2):
            with self.assertRaisesRegex(
                RestartUnavailableError,
                "Could not schedule TheCakeIsAPI restart: timer unavailable",
            ):
                restarter.request_restart()


class RestartApiTests(unittest.TestCase):
    def test_endpoint_accepts_only_an_empty_request(self) -> None:
        for extra_field in (
            {"service": "another.service"},
            {"command": "shutdown now"},
        ):
            with self.subTest(extra_field=extra_field):
                with self.assertRaises(ValidationError):
                    RestartRequest(**extra_field)

    def test_endpoint_rejects_query_parameters(self) -> None:
        restarter = ApplicationRestarter(
            enabled=True,
            systemd_managed=True,
            timer_factory=FakeTimerFactory(),
        )
        with temporary_settings_app() as (app, _config_path):
            app.state.application_restarter = restarter
            endpoint = route_endpoint(app, "/api/system/restart", "POST")

            with self.assertRaises(HTTPException) as raised:
                endpoint(
                    SimpleNamespace(query_params={"service": "another.service"}),
                    RestartRequest(),
                )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("does not accept query parameters", raised.exception.detail)

    def test_endpoint_schedules_restart_and_returns_accepted_response(self) -> None:
        restarter = ApplicationRestarter(
            enabled=True,
            systemd_managed=True,
            timer_factory=FakeTimerFactory(),
        )
        with temporary_settings_app() as (app, _config_path):
            app.state.application_restarter = restarter
            response = route_endpoint(app, "/api/system/restart", "POST")(
                SimpleNamespace(query_params={}),
                RestartRequest(),
            )
            route = next(
                route
                for route in app.routes
                if getattr(route, "path", None) == "/api/system/restart"
            )

        self.assertEqual(route.status_code, 202)
        self.assertEqual(response["status"], "restarting")
        self.assertIn("scheduled", response["message"])

    def test_endpoint_returns_useful_failure_when_restart_is_unavailable(self) -> None:
        with temporary_settings_app() as (app, _config_path):
            app.state.application_restarter = ApplicationRestarter(
                enabled=False,
                systemd_managed=True,
            )
            endpoint = route_endpoint(app, "/api/system/restart", "POST")

            with self.assertRaises(HTTPException) as raised:
                endpoint(SimpleNamespace(query_params={}), RestartRequest())

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("not enabled", raised.exception.detail)

    def test_endpoint_rejects_duplicate_restart_requests(self) -> None:
        restarter = ApplicationRestarter(
            enabled=True,
            systemd_managed=True,
            timer_factory=FakeTimerFactory(),
        )
        with temporary_settings_app() as (app, _config_path):
            app.state.application_restarter = restarter
            endpoint = route_endpoint(app, "/api/system/restart", "POST")
            endpoint(SimpleNamespace(query_params={}), RestartRequest())

            with self.assertRaises(HTTPException) as raised:
                endpoint(SimpleNamespace(query_params={}), RestartRequest())

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("already in progress", raised.exception.detail)

    def test_systemd_unit_enables_fixed_self_restart_without_sudo(self) -> None:
        service_unit = SERVICE_UNIT.read_text(encoding="utf-8")

        self.assertIn("Environment=THECAKEISAPI_RESTART_ENABLED=1", service_unit)
        self.assertIn("Restart=on-failure", service_unit)
        self.assertNotIn("sudo", service_unit)
        self.assertNotIn("systemctl", service_unit)


if __name__ == "__main__":
    unittest.main()
