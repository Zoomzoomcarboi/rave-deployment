"""Fixed NetworkManager operations for the RAVE management Wi-Fi interface."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import ClassVar, Protocol
from uuid import UUID

from rave_network_ipc.protocol import MAX_NETWORKS, WifiSecurity, validate_password, validate_ssid

NMCLI = "/usr/bin/nmcli"
SYSTEMCTL = "/usr/bin/systemctl"
INTERFACE = "wlan0"
PROVISIONING_PROFILE = "RAVE-Setup"
SAVED_PROFILE = "RAVE-Management"
PENDING_PROFILE = "RAVE-Management-Pending"
PREVIOUS_PROFILE = "RAVE-Management-Previous"
DHCP_SERVICE = "rave-management-dhcp.service"
COMMAND_TIMEOUT_SECONDS = 35.0


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str


class CommandRunner(Protocol):
    def run(self, command: list[str], *, timeout: float) -> CommandResult: ...

    def run_with_secret(
        self, command: list[str], *, password: str, timeout: float
    ) -> CommandResult: ...


class SubprocessRunner:
    """Run absolute, argv-only commands; secrets use an anonymous inherited file."""

    _ENVIRONMENT: ClassVar[dict[str, str]] = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    }

    def run(self, command: list[str], *, timeout: float) -> CommandResult:
        return self._run(command, timeout=timeout)

    def run_with_secret(
        self, command: list[str], *, password: str, timeout: float
    ) -> CommandResult:
        descriptor = os.memfd_create("rave-network-credential", flags=0)
        try:
            secret = f"802-11-wireless-security.psk:{validate_password(password)}\n".encode()
            os.write(descriptor, secret)
            os.lseek(descriptor, 0, os.SEEK_SET)
            complete_command = [*command, "passwd-file", f"/proc/self/fd/{descriptor}"]
            return self._run(complete_command, timeout=timeout, pass_fds=(descriptor,))
        finally:
            os.close(descriptor)

    def _run(
        self,
        command: list[str],
        *,
        timeout: float,
        pass_fds: tuple[int, ...] = (),
    ) -> CommandResult:
        if not 0 < timeout <= COMMAND_TIMEOUT_SECONDS:
            raise ValueError("command_timeout_out_of_policy")
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._ENVIRONMENT,
                pass_fds=pass_fds,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(124, "")
        return CommandResult(result.returncode, result.stdout)


@dataclass(frozen=True)
class AccessPoint:
    ssid: str
    signal_percent: int
    security: WifiSecurity
    connected: bool
    key_management: str | None = None


class NetworkManagerBackend:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or SubprocessRunner()

    def has_saved_station(self) -> bool:
        lookup_ok, saved_uuid = self._profile_uuid(SAVED_PROFILE)
        if not lookup_ok or saved_uuid is not None:
            return lookup_ok and saved_uuid is not None
        backup_ok, backup_uuid = self._profile_uuid(PREVIOUS_PROFILE)
        return backup_ok and backup_uuid is not None

    def activate_saved_station(self) -> tuple[bool, str | None, str | None]:
        profile_uuid = self._saved_profile_for_activation()
        if profile_uuid is None:
            return False, None, "saved_station_profile_failed"
        if not self._enable_wifi():
            return False, None, "wifi_radio_failed"
        if not self._stop_dhcp():
            return False, None, "ap_dhcp_stop_failed"
        result = self._nmcli(
            "connection",
            "up",
            "uuid",
            profile_uuid,
            "ifname",
            INTERFACE,
            wait=30,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return False, None, "saved_station_timeout"
        return True, self._saved_ssid(profile_uuid), None

    def connect_station(
        self, ssid: str, password: str | None
    ) -> tuple[bool, str | None, str | None]:
        selected_ssid = validate_ssid(ssid)
        access_point = next((item for item in self.scan() if item.ssid == selected_ssid), None)
        if access_point is None:
            return False, None, "ssid_not_found"
        credential_error = self._credential_error(access_point.security, password)
        if credential_error:
            return False, None, credential_error
        if not self._stop_dhcp():
            return False, None, "ap_dhcp_stop_failed"
        lookup_ok, previous_uuid = self._profile_uuid(SAVED_PROFILE)
        if not lookup_ok:
            return False, None, "station_profile_persistence_failed"
        self._delete_profile(PENDING_PROFILE)
        if not self._create_pending_profile(access_point):
            self._delete_profile(PENDING_PROFILE)
            return False, None, "station_profile_failed"
        pending_ok, pending_uuid = self._profile_uuid(PENDING_PROFILE)
        if not pending_ok or pending_uuid is None:
            self._delete_profile(PENDING_PROFILE)
            return False, None, "station_profile_failed"
        if not self._activate_pending(pending_uuid, access_point, password):
            self._delete_profile_uuid(pending_uuid)
            return False, None, "station_timeout"
        if not self._promote_pending_profile(pending_uuid, previous_uuid):
            self._rollback_promotion(pending_uuid, previous_uuid)
            return False, None, "station_profile_persistence_failed"
        return True, selected_ssid, None

    def activate_provisioning(self) -> tuple[bool, str | None]:
        if not self._enable_wifi():
            return False, "wifi_radio_failed"
        result = self._nmcli(
            "connection",
            "up",
            "id",
            PROVISIONING_PROFILE,
            "ifname",
            INTERFACE,
            wait=20,
            timeout=25,
        )
        if result.returncode != 0:
            return False, "ap_activation_failed"
        dhcp = self._runner.run(
            [SYSTEMCTL, "start", DHCP_SERVICE],
            timeout=10,
        )
        if dhcp.returncode != 0:
            return False, "ap_dhcp_failed"
        return True, None

    def scan(self) -> list[AccessPoint]:
        if not self._enable_wifi():
            raise RuntimeError("wifi_radio_failed")
        result = self._nmcli(
            "--terse",
            "--escape",
            "yes",
            "--fields",
            "SSID,SIGNAL,SECURITY,IN-USE",
            "device",
            "wifi",
            "list",
            "ifname",
            INTERFACE,
            "--rescan",
            "yes",
            wait=12,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError("wifi_scan_failed")
        strongest: dict[str, AccessPoint] = {}
        for line in result.stdout.splitlines():
            access_point = self._parse_access_point(line)
            if access_point is None:
                continue
            previous = strongest.get(access_point.ssid)
            if previous is None or access_point.signal_percent > previous.signal_percent:
                strongest[access_point.ssid] = access_point
        return sorted(
            strongest.values(),
            key=lambda item: (-item.signal_percent, item.ssid.casefold()),
        )[:MAX_NETWORKS]

    def active_station_ssid(self) -> str | None:
        if self._active_connection() != SAVED_PROFILE:
            return None
        return self._saved_ssid()

    def provisioning_ready(self) -> bool:
        if self._active_connection() != PROVISIONING_PROFILE:
            return False
        result = self._runner.run(
            [SYSTEMCTL, "is-active", "--quiet", DHCP_SERVICE],
            timeout=3,
        )
        return result.returncode == 0

    def _create_pending_profile(self, access_point: AccessPoint) -> bool:
        added = self._nmcli(
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            INTERFACE,
            "con-name",
            PENDING_PROFILE,
            "ssid",
            access_point.ssid,
            "connection.autoconnect",
            "no",
            "ipv4.method",
            "auto",
            "ipv4.never-default",
            "no",
            "ipv6.method",
            "auto",
            wait=5,
            timeout=8,
        )
        if added.returncode != 0 or access_point.key_management is None:
            return added.returncode == 0
        secured = self._nmcli(
            "connection",
            "modify",
            "id",
            PENDING_PROFILE,
            "802-11-wireless-security.key-mgmt",
            access_point.key_management,
            "802-11-wireless-security.psk-flags",
            "0",
            wait=5,
            timeout=8,
        )
        return secured.returncode == 0

    def _activate_pending(
        self,
        profile_uuid: str,
        access_point: AccessPoint,
        password: str | None,
    ) -> bool:
        command = self._nmcli_command(
            "connection",
            "up",
            "uuid",
            profile_uuid,
            "ifname",
            INTERFACE,
            wait=30,
        )
        if access_point.security == WifiSecurity.OPEN:
            result = self._runner.run(command, timeout=COMMAND_TIMEOUT_SECONDS)
        else:
            assert password is not None
            result = self._runner.run_with_secret(
                command,
                password=password,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        return result.returncode == 0

    def _promote_pending_profile(
        self,
        pending_uuid: str,
        previous_uuid: str | None,
    ) -> bool:
        if previous_uuid is not None:
            if not self._set_profile_identity(previous_uuid, PREVIOUS_PROFILE):
                return False
            if not self._profile_has_identity(previous_uuid, PREVIOUS_PROFILE):
                return False
        if not self._set_profile_identity(pending_uuid, SAVED_PROFILE):
            return False
        if not self._profile_has_identity(pending_uuid, SAVED_PROFILE):
            return False
        return previous_uuid is None or self._delete_profile_uuid(previous_uuid)

    def _rollback_promotion(self, pending_uuid: str, previous_uuid: str | None) -> None:
        self._set_profile_identity(pending_uuid, PENDING_PROFILE)
        if previous_uuid is not None:
            self._set_profile_identity(previous_uuid, SAVED_PROFILE)
        self._delete_profile_uuid(pending_uuid)

    def _saved_profile_for_activation(self) -> str | None:
        lookup_ok, profile_uuid = self._profile_uuid(SAVED_PROFILE)
        if not lookup_ok:
            return None
        if profile_uuid is None:
            backup_ok, profile_uuid = self._profile_uuid(PREVIOUS_PROFILE)
            if not backup_ok or profile_uuid is None:
                return None
        if not self._set_profile_identity(profile_uuid, SAVED_PROFILE):
            return None
        if not self._profile_has_identity(profile_uuid, SAVED_PROFILE):
            return None
        return profile_uuid

    def _set_profile_identity(self, profile_uuid: str, profile_id: str) -> bool:
        result = self._nmcli(
            "connection",
            "modify",
            "uuid",
            profile_uuid,
            "connection.id",
            profile_id,
            "connection.autoconnect",
            "no",
            wait=5,
            timeout=8,
        )
        return result.returncode == 0

    def _profile_has_identity(self, profile_uuid: str, profile_id: str) -> bool:
        return (
            self._profile_property(profile_uuid, "connection.id") == profile_id
            and self._profile_property(profile_uuid, "connection.autoconnect") == "no"
        )

    def _profile_property(self, profile_uuid: str, property_name: str) -> str | None:
        result = self._nmcli(
            "--get-values",
            property_name,
            "connection",
            "show",
            "uuid",
            profile_uuid,
            wait=2,
            timeout=3,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _profile_uuid(self, profile_id: str) -> tuple[bool, str | None]:
        result = self._nmcli(
            "--terse",
            "--escape",
            "no",
            "--fields",
            "UUID,NAME",
            "connection",
            "show",
            wait=2,
            timeout=3,
        )
        if result.returncode != 0:
            return False, None
        matches: list[str] = []
        for line in result.stdout.splitlines():
            candidate, separator, name = line.partition(":")
            if not separator or name != profile_id:
                continue
            try:
                matches.append(str(UUID(candidate)))
            except ValueError:
                return False, None
        if len(matches) > 1:
            return False, None
        return True, matches[0] if matches else None

    def _saved_ssid(self, profile_uuid: str | None = None) -> str | None:
        selector = ("uuid", profile_uuid) if profile_uuid is not None else ("id", SAVED_PROFILE)
        result = self._nmcli(
            "--get-values",
            "802-11-wireless.ssid",
            "connection",
            "show",
            *selector,
            wait=2,
            timeout=3,
        )
        candidate = result.stdout.strip()
        try:
            return validate_ssid(candidate) if result.returncode == 0 else None
        except ValueError:
            return None

    def _stop_dhcp(self) -> bool:
        result = self._runner.run([SYSTEMCTL, "stop", DHCP_SERVICE], timeout=10)
        return result.returncode == 0

    def _enable_wifi(self) -> bool:
        result = self._nmcli("radio", "wifi", "on", wait=5, timeout=8)
        return result.returncode == 0

    def _active_connection(self) -> str | None:
        result = self._nmcli(
            "--get-values",
            "GENERAL.CONNECTION",
            "device",
            "show",
            INTERFACE,
            wait=2,
            timeout=3,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _delete_profile(self, profile: str) -> None:
        self._nmcli(
            "connection",
            "delete",
            "id",
            profile,
            wait=5,
            timeout=8,
        )

    def _delete_profile_uuid(self, profile_uuid: str) -> bool:
        result = self._nmcli(
            "connection",
            "delete",
            "uuid",
            profile_uuid,
            wait=5,
            timeout=8,
        )
        return result.returncode == 0

    def _nmcli(self, *arguments: str, wait: int, timeout: float) -> CommandResult:
        return self._runner.run(
            self._nmcli_command(*arguments, wait=wait),
            timeout=timeout,
        )

    @staticmethod
    def _nmcli_command(*arguments: str, wait: int) -> list[str]:
        return [NMCLI, "--wait", str(wait), *arguments]

    @staticmethod
    def _credential_error(security: WifiSecurity, password: str | None) -> str | None:
        if security in {WifiSecurity.ENTERPRISE, WifiSecurity.UNSUPPORTED}:
            return "security_not_supported"
        if security == WifiSecurity.OPEN:
            return None if password is None else "password_not_expected"
        if password is None:
            return "password_required"
        try:
            validate_password(password)
        except ValueError:
            return "password_invalid"
        return None

    @staticmethod
    def _parse_access_point(line: str) -> AccessPoint | None:
        fields = _split_escaped_fields(line)
        if len(fields) != 4:
            return None
        ssid, signal, raw_security, in_use = fields
        try:
            valid_ssid = validate_ssid(ssid)
            signal_percent = int(signal)
        except (ValueError, UnicodeError):
            return None
        if not 0 <= signal_percent <= 100:
            return None
        security, key_management = _classify_security(raw_security)
        return AccessPoint(
            ssid=valid_ssid,
            signal_percent=signal_percent,
            security=security,
            connected=in_use == "*",
            key_management=key_management,
        )


def _split_escaped_fields(line: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


def _classify_security(raw_security: str) -> tuple[WifiSecurity, str | None]:
    normalized = raw_security.upper().strip()
    if normalized in {"", "--"}:
        return WifiSecurity.OPEN, None
    if "802.1X" in normalized or "EAP" in normalized:
        return WifiSecurity.ENTERPRISE, None
    if "WEP" in normalized:
        return WifiSecurity.UNSUPPORTED, None
    if "WPA" in normalized:
        key_management = "sae" if "WPA3" in normalized and "WPA2" not in normalized else "wpa-psk"
        return WifiSecurity.WPA_PERSONAL, key_management
    return WifiSecurity.UNSUPPORTED, None
