"""Unprivileged client for the root-owned RAVE network daemon socket."""

from __future__ import annotations

import json
import socket
import struct
from pathlib import Path
from typing import Any

from .protocol import (
    API_VERSION,
    MAX_NETWORKS,
    MAX_RESPONSE_BYTES,
    SOCKET_PATH,
    NetworkAction,
    NetworkMode,
    WifiSecurity,
    validate_password,
    validate_ssid,
)


class NetworkdUnavailable(RuntimeError):
    """The narrow management-network boundary is unavailable or rejected a request."""


class NetworkdClient:
    def __init__(
        self,
        socket_path: Path = Path(SOCKET_PATH),
        *,
        expected_server_uid: int = 0,
    ) -> None:
        self._socket_path = socket_path
        self._expected_server_uid = expected_server_uid

    def status(self) -> dict[str, Any]:
        return validate_status_response(self._request(NetworkAction.STATUS, timeout=1.0))

    def scan(self) -> dict[str, Any]:
        return validate_scan_response(self._request(NetworkAction.SCAN, timeout=30.0))

    def connect(self, ssid: str, password: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {"ssid": validate_ssid(ssid), "password": None}
        if password is not None:
            payload["password"] = validate_password(password)
        return validate_action_response(
            self._request(NetworkAction.CONNECT, payload, timeout=2.0)
        )

    def provisioning(self) -> dict[str, Any]:
        return validate_action_response(
            self._request(NetworkAction.PROVISIONING, timeout=2.0)
        )

    def _request(
        self,
        action: NetworkAction,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        request = {"api_version": API_VERSION, "action": action, **(payload or {})}
        serialized = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(timeout)
                connection.connect(str(self._socket_path))
                self._validate_server(connection)
                connection.sendall(serialized + b"\n")
                connection.shutdown(socket.SHUT_WR)
                response = self._receive(connection)
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            raise NetworkdUnavailable("network_management_unavailable") from error
        if not isinstance(response, dict) or response.get("api_version") != API_VERSION:
            raise NetworkdUnavailable("network_management_invalid_response")
        if response.get("ok") is not True:
            reason = response.get("error")
            if not _required_reason(reason):
                reason = "network_management_rejected"
            raise NetworkdUnavailable(reason)
        return response

    def _validate_server(self, connection: socket.socket) -> None:
        credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        _, server_uid, _ = struct.unpack("3i", credentials)
        if server_uid != self._expected_server_uid:
            raise NetworkdUnavailable("network_management_peer_invalid")

    @staticmethod
    def _receive(connection: socket.socket) -> dict[str, Any]:
        chunks: list[bytes] = []
        received = 0
        while True:
            chunk = connection.recv(min(4096, MAX_RESPONSE_BYTES + 1 - received))
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
            if received > MAX_RESPONSE_BYTES:
                raise ValueError("network_management_response_too_large")
        return json.loads(b"".join(chunks))


STATUS_RESPONSE_FIELDS = {
    "api_version",
    "ok",
    "mode",
    "provisioning_ap_active",
    "station_ssid",
    "last_error",
}


def validate_status_response(response: dict[str, Any]) -> dict[str, Any]:
    if set(response) != STATUS_RESPONSE_FIELDS:
        raise NetworkdUnavailable("network_management_invalid_response")
    try:
        NetworkMode(response["mode"])
        if response["station_ssid"] is not None:
            validate_ssid(response["station_ssid"])
    except (TypeError, ValueError) as error:
        raise NetworkdUnavailable("network_management_invalid_response") from error
    if type(response["provisioning_ap_active"]) is not bool:
        raise NetworkdUnavailable("network_management_invalid_response")
    if not _optional_reason(response["last_error"]):
        raise NetworkdUnavailable("network_management_invalid_response")
    return response


def validate_scan_response(response: dict[str, Any]) -> dict[str, Any]:
    if set(response) != {"api_version", "ok", "networks"}:
        raise NetworkdUnavailable("network_management_invalid_response")
    networks = response["networks"]
    if not isinstance(networks, list) or len(networks) > MAX_NETWORKS:
        raise NetworkdUnavailable("network_management_invalid_response")
    for network in networks:
        _validate_network(network)
    return response


def validate_action_response(response: dict[str, Any]) -> dict[str, Any]:
    status = {key: value for key, value in response.items() if key not in {"accepted", "reason"}}
    validate_status_response(status)
    if set(response) != STATUS_RESPONSE_FIELDS | {"accepted", "reason"}:
        raise NetworkdUnavailable("network_management_invalid_response")
    if type(response["accepted"]) is not bool or not _required_reason(response["reason"]):
        raise NetworkdUnavailable("network_management_invalid_response")
    return response


def _validate_network(network: object) -> None:
    if not isinstance(network, dict) or set(network) != {
        "ssid",
        "signal_percent",
        "security",
        "connected",
    }:
        raise NetworkdUnavailable("network_management_invalid_response")
    try:
        validate_ssid(network["ssid"])
        WifiSecurity(network["security"])
    except (TypeError, ValueError) as error:
        raise NetworkdUnavailable("network_management_invalid_response") from error
    signal = network["signal_percent"]
    if type(signal) is not int or not 0 <= signal <= 100 or type(network["connected"]) is not bool:
        raise NetworkdUnavailable("network_management_invalid_response")


def _required_reason(value: object) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 64 and "\n" not in value


def _optional_reason(value: object) -> bool:
    return value is None or _required_reason(value)
