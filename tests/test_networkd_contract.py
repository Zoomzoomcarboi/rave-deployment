import json
import logging
import os
import struct

import pytest
from rave_network_ipc.client import (
    NetworkdUnavailable,
    validate_action_response,
    validate_scan_response,
    validate_status_response,
)
from rave_network_ipc.protocol import API_VERSION, NetworkAction, WifiSecurity
from rave_networkd.backend import (
    NMCLI,
    PENDING_PROFILE,
    PREVIOUS_PROFILE,
    SAVED_PROFILE,
    SYSTEMCTL,
    CommandResult,
    NetworkManagerBackend,
)
from rave_networkd.controller import NetworkController, NetworkSnapshot
from rave_networkd.server import (
    REQUEST_FRAMING_TIMEOUT_SECONDS,
    NetworkdServer,
    ProtocolError,
    parse_request,
)
from rave_web.models import NetworkMode


class FakeRunner:
    def __init__(self, results: list[CommandResult] | None = None) -> None:
        self.results = list(results or [])
        self.commands: list[tuple[tuple[str, ...], float]] = []
        self.secret_commands: list[tuple[tuple[str, ...], str, float]] = []

    def run(self, command: list[str], *, timeout: float) -> CommandResult:
        self.commands.append((tuple(command), timeout))
        return self.results.pop(0) if self.results else CommandResult(0, "")

    def run_with_secret(
        self, command: list[str], *, password: str, timeout: float
    ) -> CommandResult:
        self.secret_commands.append((tuple(command), password, timeout))
        return self.results.pop(0) if self.results else CommandResult(0, "")


OLD_PROFILE_UUID = "11111111-1111-4111-8111-111111111111"
NEW_PROFILE_UUID = "22222222-2222-4222-8222-222222222222"


class ProfileRunner:
    def __init__(
        self,
        *,
        previous: bool = True,
        fail_at: str | set[str] | None = None,
    ) -> None:
        self.profiles: dict[str, dict[str, str]] = {}
        if previous:
            self.profiles[OLD_PROFILE_UUID] = {
                "id": SAVED_PROFILE,
                "autoconnect": "no",
                "ssid": "Previous",
            }
        self.fail_at = {fail_at} if isinstance(fail_at, str) else set(fail_at or ())
        self.injected_failures: set[str] = set()
        self.failure_injected = False
        self.commands: list[tuple[tuple[str, ...], float]] = []
        self.secret_commands: list[tuple[tuple[str, ...], str, float]] = []
        self.activated_uuid: str | None = None
        self.profile_list_calls = 0

    def run(self, command: list[str], *, timeout: float) -> CommandResult:
        self.commands.append((tuple(command), timeout))
        return self._execute(command)

    def run_with_secret(
        self, command: list[str], *, password: str, timeout: float
    ) -> CommandResult:
        self.secret_commands.append((tuple(command), password, timeout))
        return self._execute(command)

    def _execute(self, command: list[str]) -> CommandResult:
        if command[0] == SYSTEMCTL:
            return CommandResult(0, "")
        assert command[0] == NMCLI
        arguments = command[3:]
        return self._execute_nmcli(arguments)

    def _execute_nmcli(self, arguments: list[str]) -> CommandResult:
        if arguments[:3] == ["radio", "wifi", "on"]:
            return CommandResult(0, "")
        if "device" in arguments and "wifi" in arguments:
            return CommandResult(0, "New:90:WPA2:\n")
        if arguments[-2:] == ["connection", "show"]:
            return self._list_profiles()
        if arguments[:2] == ["connection", "add"]:
            return self._add_pending_profile()
        if arguments[:2] == ["connection", "modify"]:
            return self._modify(arguments)
        if arguments[:2] == ["connection", "up"]:
            profile_uuid = arguments[3]
            label = "activate_new" if profile_uuid == NEW_PROFILE_UUID else "activate_saved"
            if self._inject(label):
                return CommandResult(1, "")
            self.activated_uuid = profile_uuid
            return CommandResult(0, "")
        if arguments[:2] == ["connection", "delete"]:
            return self._delete(arguments)
        if arguments[0] == "--get-values":
            return self._profile_value(arguments)
        raise AssertionError(f"unexpected command: {arguments!r}")

    def _list_profiles(self) -> CommandResult:
        self.profile_list_calls += 1
        label = "lookup_previous" if self.profile_list_calls == 1 else "lookup_pending"
        if self._inject(label):
            return CommandResult(1, "")
        profiles = "".join(
            f"{profile_uuid}:{profile['id']}\n"
            for profile_uuid, profile in self.profiles.items()
        )
        return CommandResult(0, profiles)

    def _add_pending_profile(self) -> CommandResult:
        if self._inject("create_pending"):
            return CommandResult(1, "")
        self.profiles[NEW_PROFILE_UUID] = {
            "id": PENDING_PROFILE,
            "autoconnect": "no",
            "ssid": "New",
        }
        return CommandResult(0, "")

    def _profile_value(self, arguments: list[str]) -> CommandResult:
        if arguments[:2] == ["--get-values", "802-11-wireless.ssid"]:
            return CommandResult(0, self.profiles[arguments[-1]]["ssid"])
        property_name = arguments[1]
        profile_uuid = arguments[-1]
        profile = self.profiles[profile_uuid]
        suffix = "id" if property_name == "connection.id" else "autoconnect"
        owner = "new" if profile_uuid == NEW_PROFILE_UUID else "old"
        if self._inject(f"verify_{owner}_{suffix}"):
            return CommandResult(1, "")
        key = "id" if suffix == "id" else "autoconnect"
        return CommandResult(0, profile[key])

    def _modify(self, arguments: list[str]) -> CommandResult:
        if arguments[2:4] == ["id", PENDING_PROFILE]:
            return CommandResult(0, "")
        profile_uuid = arguments[3]
        profile_id = arguments[5]
        if profile_uuid == NEW_PROFILE_UUID and profile_id == SAVED_PROFILE:
            label = "promote_new"
        elif profile_uuid == OLD_PROFILE_UUID and profile_id == PREVIOUS_PROFILE:
            label = "backup_old"
        elif profile_uuid == NEW_PROFILE_UUID and profile_id == PENDING_PROFILE:
            label = "rollback_new"
        elif profile_uuid == OLD_PROFILE_UUID and profile_id == SAVED_PROFILE:
            label = "rollback_old"
        else:
            raise AssertionError(f"unexpected profile identity change: {arguments!r}")
        if self._inject(label):
            return CommandResult(1, "")
        self.profiles[profile_uuid]["id"] = profile_id
        self.profiles[profile_uuid]["autoconnect"] = arguments[7]
        return CommandResult(0, "")

    def _delete(self, arguments: list[str]) -> CommandResult:
        selector, value = arguments[2:4]
        if selector == "uuid":
            if value == OLD_PROFILE_UUID and self._inject("delete_old"):
                return CommandResult(1, "")
            self.profiles.pop(value, None)
        else:
            for profile_uuid in [
                item for item, profile in self.profiles.items() if profile["id"] == value
            ]:
                del self.profiles[profile_uuid]
        return CommandResult(0, "")

    def _inject(self, label: str) -> bool:
        if label not in self.fail_at or label in self.injected_failures:
            return False
        self.injected_failures.add(label)
        self.failure_injected = True
        return True


class PromotionInterrupted(BaseException):
    pass


class InterruptBeforePromotionRunner(ProfileRunner):
    def _modify(self, arguments: list[str]) -> CommandResult:
        if arguments[3:6] == [NEW_PROFILE_UUID, "connection.id", SAVED_PROFILE]:
            raise PromotionInterrupted
        return super()._modify(arguments)

class FakeBackend:
    def __init__(
        self,
        *,
        saved: bool = False,
        station_success: bool = True,
        ap_success: bool = True,
        station_active: bool = True,
        provisioning_active: bool = True,
    ):
        self.saved = saved
        self.station_success = station_success
        self.ap_success = ap_success
        self.station_active = station_active
        self.provisioning_active = provisioning_active
        self.calls: list[tuple[str, str | None]] = []

    def has_saved_station(self) -> bool:
        self.calls.append(("has_saved_station", None))
        return self.saved

    def activate_saved_station(self):
        self.calls.append(("activate_saved_station", None))
        return self.station_success, "Saved Wi-Fi" if self.station_success else None, "station_timeout"

    def connect_station(self, ssid: str, password: str | None):
        self.calls.append(("connect_station", ssid))
        return self.station_success, ssid if self.station_success else None, "station_timeout"

    def activate_provisioning(self) -> tuple[bool, str | None]:
        self.calls.append(("activate_provisioning", None))
        return self.ap_success, None if self.ap_success else "ap_activation_failed"

    def scan(self):
        self.calls.append(("scan", None))
        return []

    def active_station_ssid(self) -> str | None:
        self.calls.append(("active_station_ssid", None))
        return "Home" if self.station_active else None

    def provisioning_ready(self) -> bool:
        self.calls.append(("provisioning_ready", None))
        return self.provisioning_active


class RaisingConnectBackend(FakeBackend):
    def connect_station(self, ssid: str, password: str | None):
        del ssid, password
        raise OSError("synthetic NetworkManager failure")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class DripConnection:
    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.timeouts: list[float] = []
        self.recv_calls = 0

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def recv(self, _size: int) -> bytes:
        self.recv_calls += 1
        self._clock.now += min(0.75, self.timeouts[-1])
        return b"x"


class RequestConnection:
    def __init__(self, request: bytes) -> None:
        self._request = request
        self.response = b""

    @staticmethod
    def getsockopt(_level: int, _option: int, _length: int) -> bytes:
        return struct.pack("3i", 0, os.getuid(), 0)

    @staticmethod
    def settimeout(_timeout: float) -> None:
        pass

    def recv(self, size: int) -> bytes:
        chunk = self._request[:size]
        self._request = self._request[size:]
        return chunk

    def sendall(self, response: bytes) -> None:
        self.response = response


class UnexpectedBackendFailure(Exception):
    pass


class FailingThenRecoveringController:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    def request_connect(self, _ssid: str, _password: str | None) -> NetworkSnapshot:
        raise self._error

    @staticmethod
    def snapshot() -> NetworkSnapshot:
        return NetworkSnapshot(NetworkMode.PROVISIONING_AP, True, None, None)


def serve_request(server: NetworkdServer, payload: dict[str, object]) -> dict[str, object]:
    serialized = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
    connection = RequestConnection(serialized)
    server._serve_connection(connection)  # type: ignore[arg-type]
    return json.loads(connection.response)


def test_ipc_rejects_generic_commands_interfaces_and_property_dictionaries() -> None:
    for payload in (
        {"api_version": "v1", "action": "nmcli", "args": ["general"]},
        {"api_version": "v1", "action": NetworkAction.SCAN, "interface": "eth0"},
        {
            "api_version": "v1",
            "action": NetworkAction.CONNECT,
            "ssid": "RAVE",
            "password": "correct-horse",
            "properties": {"ipv4.method": "shared"},
        },
    ):
        with pytest.raises(ProtocolError):
            parse_request(payload)


def test_request_framing_timeout_is_one_total_monotonic_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    connection = DripConnection(clock)
    monkeypatch.setattr("rave_networkd.server.time.monotonic", clock.monotonic)

    with pytest.raises(ProtocolError, match="^request_timeout$"):
        NetworkdServer._receive_request(connection)  # type: ignore[arg-type]

    assert clock.now == pytest.approx(REQUEST_FRAMING_TIMEOUT_SECONDS)
    assert connection.recv_calls == 3
    assert connection.timeouts == pytest.approx([2.0, 1.25, 0.5])


@pytest.mark.parametrize(
    "failure",
    [
        UnexpectedBackendFailure("correct-horse"),
        RuntimeError("correct-horse"),
    ],
)
def test_unexpected_request_failure_is_sanitized_and_next_request_works(
    failure: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="rave-networkd")
    server = NetworkdServer(
        FailingThenRecoveringController(failure),  # type: ignore[arg-type]
        allowed_uid=os.getuid(),
    )
    connect = {
        "api_version": API_VERSION,
        "action": NetworkAction.CONNECT,
        "ssid": "Home",
        "password": "correct-horse",
    }

    rejected = serve_request(server, connect)
    recovered = serve_request(
        server, {"api_version": API_VERSION, "action": NetworkAction.STATUS}
    )

    assert rejected == {"api_version": API_VERSION, "ok": False, "error": "internal_error"}
    assert recovered["ok"] is True
    assert recovered["mode"] == NetworkMode.PROVISIONING_AP
    assert "correct-horse" not in json.dumps(rejected)
    assert [record.getMessage() for record in caplog.records] == [
        f"unexpected IPC request failure ({type(failure).__name__})"
    ]
    assert "correct-horse" not in caplog.text


@pytest.mark.parametrize(
    ("failure", "expected_type"),
    [
        (KeyboardInterrupt(), KeyboardInterrupt),
        (SystemExit(), SystemExit),
    ],
)
def test_process_control_exceptions_are_not_swallowed(
    failure: BaseException,
    expected_type: type[BaseException],
) -> None:
    server = NetworkdServer(
        FailingThenRecoveringController(failure),  # type: ignore[arg-type]
        allowed_uid=os.getuid(),
    )
    request = {
        "api_version": API_VERSION,
        "action": NetworkAction.CONNECT,
        "ssid": "Home",
        "password": "correct-horse",
    }

    with pytest.raises(expected_type):
        serve_request(server, request)


def test_ipc_client_rejects_malformed_or_secret_bearing_responses() -> None:
    status = {
        "api_version": "v1",
        "ok": True,
        "mode": "provisioning_ap",
        "provisioning_ap_active": True,
        "station_ssid": None,
        "last_error": None,
    }
    assert validate_status_response(status) is status
    with pytest.raises(NetworkdUnavailable):
        validate_status_response({**status, "password": "not-returned"})
    with pytest.raises(NetworkdUnavailable):
        validate_scan_response(
            {
                "api_version": "v1",
                "ok": True,
                "networks": [
                    {
                        "ssid": "Home",
                        "signal_percent": 80,
                        "security": "wpa_personal",
                        "connected": False,
                        "psk": "not-returned",
                    }
                ],
            }
        )
    with pytest.raises(NetworkdUnavailable):
        validate_action_response(
            {
                **status,
                "accepted": True,
                "reason": "station_connection_requested",
                "command": ["nmcli", "general"],
            }
        )


def test_nmcli_commands_are_fixed_bounded_and_never_contain_password() -> None:
    runner = ProfileRunner()
    backend = NetworkManagerBackend(runner)
    success, ssid, error = backend.connect_station("New", "correct-horse")
    assert (success, ssid, error) == (True, "New", None)
    assert len(runner.secret_commands) == 1
    secret_command, secret, secret_timeout = runner.secret_commands[0]
    assert secret == "correct-horse"
    assert "correct-horse" not in " ".join(secret_command)
    assert "passwd-file" not in secret_command
    assert secret_timeout <= 35
    assert all(timeout <= 35 for _, timeout in runner.commands)
    commands = "\n".join(" ".join(command) for command, _ in runner.commands)
    assert "wlan0" in commands
    assert "eth0" not in commands
    assert "shared" not in commands
    assert "802-11-wireless-security.psk-flags 0" in commands


def test_successful_profile_promotion_is_single_canonical_and_not_autoconnected() -> None:
    runner = ProfileRunner()
    backend = NetworkManagerBackend(runner)

    assert backend.connect_station("New", "correct-horse") == (True, "New", None)

    assert runner.profiles == {
        NEW_PROFILE_UUID: {
            "id": SAVED_PROFILE,
            "autoconnect": "no",
            "ssid": "New",
        }
    }
    commands = "\n".join(" ".join(command) for command, _timeout in runner.commands)
    assert "connection.autoconnect yes" not in commands
    assert "connection.autoconnect-retries" not in commands

    assert backend.has_saved_station() is True
    assert backend.activate_saved_station() == (True, "New", None)
    assert runner.activated_uuid == NEW_PROFILE_UUID


def test_failed_candidate_activation_deletes_candidate_and_preserves_saved_profile() -> None:
    runner = ProfileRunner(fail_at="activate_new")

    result = NetworkManagerBackend(runner).connect_station("New", "correct-horse")

    assert result == (False, None, "station_timeout")
    assert runner.profiles == {
        OLD_PROFILE_UUID: {
            "id": SAVED_PROFILE,
            "autoconnect": "no",
            "ssid": "Previous",
        }
    }


@pytest.mark.parametrize(
    "failure_boundary",
    [
        "promote_new",
        "verify_new_id",
        "verify_new_autoconnect",
        "backup_old",
        "verify_old_id",
        "verify_old_autoconnect",
        "delete_old",
    ],
)
def test_promotion_failure_restores_previous_profile_and_removes_candidate(
    failure_boundary: str,
) -> None:
    runner = ProfileRunner(fail_at=failure_boundary)
    backend = NetworkManagerBackend(runner)

    result = backend.connect_station("New", "correct-horse")

    assert result == (False, None, "station_profile_persistence_failed")
    assert runner.failure_injected is True
    assert runner.profiles == {
        OLD_PROFILE_UUID: {
            "id": SAVED_PROFILE,
            "autoconnect": "no",
            "ssid": "Previous",
        }
    }
    assert backend.has_saved_station() is True
    assert backend.activate_saved_station() == (True, "Previous", None)
    assert runner.activated_uuid == OLD_PROFILE_UUID


def test_first_saved_profile_promotes_without_requiring_a_previous_profile() -> None:
    runner = ProfileRunner(previous=False)

    result = NetworkManagerBackend(runner).connect_station("New", "correct-horse")

    assert result == (True, "New", None)
    assert runner.profiles[NEW_PROFILE_UUID]["id"] == SAVED_PROFILE
    assert runner.profiles[NEW_PROFILE_UUID]["autoconnect"] == "no"


def test_interrupted_promotion_restores_previous_profile_on_next_boot() -> None:
    runner = InterruptBeforePromotionRunner()
    backend = NetworkManagerBackend(runner)

    with pytest.raises(PromotionInterrupted):
        backend.connect_station("New", "correct-horse")

    assert runner.profiles[OLD_PROFILE_UUID]["id"] == PREVIOUS_PROFILE
    assert runner.profiles[NEW_PROFILE_UUID]["id"] == PENDING_PROFILE
    assert backend.has_saved_station() is True
    assert backend.activate_saved_station() == (True, "Previous", None)
    assert runner.profiles[OLD_PROFILE_UUID]["id"] == SAVED_PROFILE
    assert runner.activated_uuid == OLD_PROFILE_UUID


def test_boot_recovers_previous_profile_identity_and_explicitly_activates_uuid() -> None:
    runner = ProfileRunner(previous=False)
    runner.profiles[OLD_PROFILE_UUID] = {
        "id": PREVIOUS_PROFILE,
        "autoconnect": "no",
        "ssid": "Previous",
    }
    backend = NetworkManagerBackend(runner)

    assert backend.has_saved_station() is True
    assert backend.activate_saved_station() == (True, "Previous", None)

    assert runner.profiles[OLD_PROFILE_UUID]["id"] == SAVED_PROFILE
    assert runner.profiles[OLD_PROFILE_UUID]["autoconnect"] == "no"
    assert runner.activated_uuid == OLD_PROFILE_UUID


def test_boot_disables_legacy_saved_profile_autoconnect_before_explicit_activation() -> None:
    runner = ProfileRunner()
    runner.profiles[OLD_PROFILE_UUID]["autoconnect"] = "yes"
    backend = NetworkManagerBackend(runner)

    assert backend.activate_saved_station() == (True, "Previous", None)

    assert runner.profiles[OLD_PROFILE_UUID]["autoconnect"] == "no"
    assert runner.activated_uuid == OLD_PROFILE_UUID


def test_interrupted_rollback_preserves_backup_for_next_boot_recovery() -> None:
    runner = ProfileRunner(fail_at={"delete_old", "rollback_old"})
    backend = NetworkManagerBackend(runner)

    result = backend.connect_station("New", "correct-horse")

    assert result == (False, None, "station_profile_persistence_failed")
    assert NEW_PROFILE_UUID not in runner.profiles
    assert runner.profiles[OLD_PROFILE_UUID]["id"] == PREVIOUS_PROFILE
    assert backend.has_saved_station() is True
    assert backend.activate_saved_station() == (True, "Previous", None)
    assert runner.profiles[OLD_PROFILE_UUID]["id"] == SAVED_PROFILE
    assert runner.activated_uuid == OLD_PROFILE_UUID


def test_scan_is_sanitized_deduplicated_and_classified() -> None:
    runner = FakeRunner(
        [
            CommandResult(0, ""),
            CommandResult(
                0,
                "Home\\:WiFi:30:WPA2:\n"
                "Home\\:WiFi:80:WPA2:*\n"
                ":90:WPA2:\n"
                "Guest:70:--:\n"
                "Corp:60:WPA2 802.1X:\n",
            )
        ]
    )
    networks = NetworkManagerBackend(runner).scan()
    assert [(network.ssid, network.signal_percent, network.security, network.connected) for network in networks] == [
        ("Home:WiFi", 80, WifiSecurity.WPA_PERSONAL, True),
        ("Guest", 70, WifiSecurity.OPEN, False),
        ("Corp", 60, WifiSecurity.ENTERPRISE, False),
    ]


def test_scan_failure_is_distinct_from_an_empty_scan() -> None:
    runner = FakeRunner([CommandResult(0, ""), CommandResult(10, "")])
    with pytest.raises(RuntimeError, match="wifi_scan_failed"):
        NetworkManagerBackend(runner).scan()


def test_station_transition_does_not_continue_if_ap_dhcp_cannot_stop() -> None:
    runner = FakeRunner(
        [
            CommandResult(0, ""),
            CommandResult(0, "Home:90:WPA2:\n"),
            CommandResult(1, ""),
        ]
    )
    result = NetworkManagerBackend(runner).connect_station("Home", "correct-horse")
    assert result == (False, None, "ap_dhcp_stop_failed")
    commands = [command for command, _timeout in runner.commands]
    assert not any("connection" in command and "add" in command for command in commands)


def test_failed_station_transition_restores_verified_provisioning_ap() -> None:
    backend = FakeBackend(station_success=False)
    controller = NetworkController(backend)
    controller.request_boot()
    controller.process_next()
    assert controller.snapshot().mode == NetworkMode.PROVISIONING_AP
    controller.request_connect("Unavailable Wi-Fi", "correct-horse")
    assert controller.snapshot().mode == NetworkMode.TRANSITION
    controller.process_next()
    snapshot = controller.snapshot()
    assert snapshot.mode == NetworkMode.PROVISIONING_AP
    assert snapshot.provisioning_ap_active is True
    assert snapshot.last_error == "station_timeout"
    assert backend.calls[-1] == ("activate_provisioning", None)


def test_boot_explicitly_attempts_saved_station_activation() -> None:
    backend = FakeBackend(saved=True, station_success=True)
    controller = NetworkController(backend)

    controller.request_boot()
    controller.process_next()

    assert backend.calls[:2] == [
        ("has_saved_station", None),
        ("activate_saved_station", None),
    ]
    assert controller.snapshot().mode == NetworkMode.STATION_CONNECTED


def test_promotion_failure_recovers_provisioning_without_nm_autoconnect() -> None:
    runner = ProfileRunner(fail_at="promote_new")
    controller = NetworkController(NetworkManagerBackend(runner))
    controller.request_boot()
    controller.process_next()
    controller.request_connect("New", "correct-horse")

    controller.process_next()

    snapshot = controller.snapshot()
    assert snapshot.mode == NetworkMode.PROVISIONING_AP
    assert snapshot.provisioning_ap_active is True
    assert snapshot.last_error == "station_profile_persistence_failed"
    assert runner.activated_uuid == "RAVE-Setup"


def test_successful_station_transition_persists_connected_state() -> None:
    backend = FakeBackend(station_success=True)
    controller = NetworkController(backend)
    controller.request_boot()
    controller.process_next()
    controller.request_connect("Home", "correct-horse")
    controller.process_next()
    snapshot = controller.snapshot()
    assert snapshot.mode == NetworkMode.STATION_CONNECTED
    assert snapshot.station_ssid == "Home"
    assert snapshot.provisioning_ap_active is False
    assert snapshot.last_error is None


def test_rejected_overlapping_request_is_not_left_in_work_queue() -> None:
    backend = FakeBackend(station_success=True)
    controller = NetworkController(backend)
    controller.request_boot()
    controller.process_next()
    controller.request_connect("Home", "correct-horse")
    with pytest.raises(ValueError, match="invalid network transition"):
        controller.request_connect("Second", "correct-horse")
    controller.process_next()
    assert controller.snapshot().mode == NetworkMode.STATION_CONNECTED
    assert controller.process_next(timeout=0) is False
    assert ("connect_station", "Second") not in backend.calls


def test_scan_is_rejected_while_a_state_transition_is_pending() -> None:
    backend = FakeBackend()
    controller = NetworkController(backend)
    controller.request_boot()
    with pytest.raises(RuntimeError, match="network_transition_busy"):
        controller.scan()
    assert ("scan", None) not in backend.calls


def test_station_loss_is_reconciled_to_provisioning_ap() -> None:
    backend = FakeBackend(station_success=True, station_active=False)
    controller = NetworkController(backend)
    controller.request_boot()
    controller.process_next()
    controller.request_connect("Home", "correct-horse")
    controller.process_next()
    controller.reconcile()
    snapshot = controller.snapshot()
    assert snapshot.mode == NetworkMode.PROVISIONING_AP
    assert snapshot.provisioning_ap_active is True
    assert snapshot.last_error == "station_connection_lost"


def test_provisioning_loss_is_reactivated_and_reported() -> None:
    backend = FakeBackend(provisioning_active=False)
    controller = NetworkController(backend)
    controller.request_boot()
    controller.process_next()
    controller.reconcile()
    snapshot = controller.snapshot()
    assert snapshot.mode == NetworkMode.PROVISIONING_AP
    assert snapshot.provisioning_ap_active is True
    assert snapshot.last_error == "provisioning_ap_lost"


def test_unexpected_transition_failure_still_recovers_provisioning_ap() -> None:
    controller = NetworkController(RaisingConnectBackend())
    controller.request_boot()
    controller.process_next()
    controller.request_connect("Home", "correct-horse")
    with pytest.raises(OSError, match="synthetic NetworkManager failure"):
        controller.process_next()
    snapshot = controller.snapshot()
    assert snapshot.mode == NetworkMode.PROVISIONING_AP
    assert snapshot.provisioning_ap_active is True
    assert snapshot.last_error == "network_operation_failed"


def test_password_is_not_logged_on_failure(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    backend = FakeBackend(station_success=False)
    controller = NetworkController(backend)
    controller.request_boot()
    controller.process_next()
    controller.request_connect("Home", "correct-horse")
    controller.process_next()
    assert "correct-horse" not in caplog.text
