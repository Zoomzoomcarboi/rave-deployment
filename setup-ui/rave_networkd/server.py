"""Root-owned local IPC server exposing only reviewed management Wi-Fi actions."""

from __future__ import annotations

import argparse
import json
import logging
import pwd
import signal
import socket
import stat
import struct
import threading
import time
from pathlib import Path
from typing import Any

from rave_network_ipc.protocol import (
    API_VERSION,
    MAX_REQUEST_BYTES,
    SOCKET_PATH,
    NetworkAction,
    validate_password,
    validate_ssid,
)

from .backend import NetworkManagerBackend
from .controller import NetworkController, NetworkSnapshot

LOGGER = logging.getLogger("rave-networkd")
RECONCILE_INTERVAL_SECONDS = 10.0
REQUEST_FRAMING_TIMEOUT_SECONDS = 2.0

PUBLIC_PROTOCOL_ERROR_CODES = frozenset(
    {
        "action_invalid",
        "api_version_invalid",
        "network_credentials_invalid",
        "peer_not_authorized",
        "request_empty",
        "request_fields_invalid",
        "request_not_object",
        "request_timeout",
        "request_too_large",
    }
)
PUBLIC_OPERATION_ERROR_CODES = frozenset({"network_transition_busy"})


class ProtocolError(ValueError):
    pass


def parse_request(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProtocolError("request_not_object")
    if payload.get("api_version") != API_VERSION:
        raise ProtocolError("api_version_invalid")
    try:
        action = NetworkAction(payload.get("action"))
    except (TypeError, ValueError) as error:
        raise ProtocolError("action_invalid") from error
    expected = {
        NetworkAction.STATUS: {"api_version", "action"},
        NetworkAction.SCAN: {"api_version", "action"},
        NetworkAction.CONNECT: {"api_version", "action", "ssid", "password"},
        NetworkAction.PROVISIONING: {"api_version", "action"},
    }[action]
    if set(payload) != expected:
        raise ProtocolError("request_fields_invalid")
    parsed: dict[str, Any] = {"action": action}
    if action == NetworkAction.CONNECT:
        try:
            parsed["ssid"] = validate_ssid(payload["ssid"])
            password = payload["password"]
            parsed["password"] = None if password is None else validate_password(password)
        except (KeyError, TypeError, ValueError) as error:
            raise ProtocolError("network_credentials_invalid") from error
    return parsed


class NetworkdServer:
    def __init__(
        self,
        controller: NetworkController,
        *,
        socket_path: Path = Path(SOCKET_PATH),
        allowed_uid: int,
    ) -> None:
        self._controller = controller
        self._socket_path = socket_path
        self._allowed_uid = allowed_uid
        self._stopping = threading.Event()

    def serve(self) -> None:
        worker = threading.Thread(target=self._work_loop, name="network-transition", daemon=True)
        worker.start()
        self._controller.request_boot()
        with self._create_socket() as listener:
            listener.settimeout(1.0)
            while not self._stopping.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    self._serve_connection(connection)

    def stop(self, *_unused: object) -> None:
        self._stopping.set()

    def _work_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                if not self._controller.process_next(timeout=RECONCILE_INTERVAL_SECONDS):
                    self._controller.reconcile()
            except Exception:
                LOGGER.exception("bounded management network transition failed")

    def _create_socket(self) -> socket.socket:
        self._socket_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        try:
            existing = self._socket_path.lstat()
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(existing.st_mode):
                raise RuntimeError("networkd_socket_path_is_not_a_socket")
            self._socket_path.unlink()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self._socket_path))
        self._socket_path.chmod(0o660)
        listener.listen(4)
        return listener

    def _serve_connection(self, connection: socket.socket) -> None:
        try:
            if self._peer_uid(connection) != self._allowed_uid:
                raise ProtocolError("peer_not_authorized")
            payload = json.loads(self._receive_request(connection))
            response = self._dispatch(parse_request(payload))
        except ProtocolError as error:
            response = self._error_response(error, PUBLIC_PROTOCOL_ERROR_CODES)
        except json.JSONDecodeError:
            response = self._error_response_code("request_json_invalid")
        except RuntimeError as error:
            response = self._error_response(error, PUBLIC_OPERATION_ERROR_CODES)
        except Exception as error:  # noqa: BLE001 - final daemon request boundary
            response = self._internal_error_response(error)
        try:
            connection.sendall(json.dumps(response, separators=(",", ":")).encode())
        except OSError:
            # A disappearing web client must not terminate the privileged daemon.
            return

    @classmethod
    def _error_response(
        cls, error: Exception, public_codes: frozenset[str]
    ) -> dict[str, Any]:
        code = str(error)
        if code in public_codes:
            return cls._error_response_code(code)
        return cls._internal_error_response(error)

    @staticmethod
    def _error_response_code(code: str) -> dict[str, Any]:
        return {"api_version": API_VERSION, "ok": False, "error": code}

    @classmethod
    def _internal_error_response(cls, error: Exception) -> dict[str, Any]:
        # Exception messages may contain privileged backend details or credentials.
        LOGGER.error("unexpected IPC request failure (%s)", type(error).__name__)
        return cls._error_response_code("internal_error")

    def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request["action"]
        if action == NetworkAction.STATUS:
            return self._snapshot_response(self._controller.snapshot())
        if action == NetworkAction.SCAN:
            networks = [
                {
                    "ssid": item.ssid,
                    "signal_percent": item.signal_percent,
                    "security": item.security,
                    "connected": item.connected,
                }
                for item in self._controller.scan()
            ]
            return {"api_version": API_VERSION, "ok": True, "networks": networks}
        if action == NetworkAction.CONNECT:
            snapshot = self._controller.request_connect(request["ssid"], request["password"])
            response = self._snapshot_response(snapshot)
            response.update({"accepted": True, "reason": "station_connection_requested"})
            return response
        snapshot = self._controller.request_provisioning()
        response = self._snapshot_response(snapshot)
        response.update({"accepted": True, "reason": "provisioning_ap_requested"})
        return response

    @staticmethod
    def _snapshot_response(snapshot: NetworkSnapshot) -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "ok": True,
            "mode": snapshot.mode,
            "provisioning_ap_active": snapshot.provisioning_ap_active,
            "station_ssid": snapshot.station_ssid,
            "last_error": snapshot.last_error,
        }

    @staticmethod
    def _peer_uid(connection: socket.socket) -> int:
        credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        _, uid, _ = struct.unpack("3i", credentials)
        return uid

    @staticmethod
    def _receive_request(connection: socket.socket) -> bytes:
        request = bytearray()
        deadline = time.monotonic() + REQUEST_FRAMING_TIMEOUT_SECONDS
        while len(request) <= MAX_REQUEST_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProtocolError("request_timeout")
            connection.settimeout(remaining)
            try:
                chunk = connection.recv(min(1024, MAX_REQUEST_BYTES + 1 - len(request)))
            except TimeoutError as error:
                raise ProtocolError("request_timeout") from error
            if not chunk:
                break
            request.extend(chunk)
            if b"\n" in chunk:
                break
        if len(request) > MAX_REQUEST_BYTES:
            raise ProtocolError("request_too_large")
        serialized = bytes(request).split(b"\n", 1)[0]
        if not serialized:
            raise ProtocolError("request_empty")
        return serialized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, default=Path(SOCKET_PATH))
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(levelname)s: %(message)s")
    args = parse_args()
    allowed_uid = pwd.getpwnam("rave").pw_uid
    server = NetworkdServer(
        NetworkController(NetworkManagerBackend()),
        socket_path=args.socket,
        allowed_uid=allowed_uid,
    )
    signal.signal(signal.SIGTERM, server.stop)
    signal.signal(signal.SIGINT, server.stop)
    try:
        server.serve()
    finally:
        try:
            if stat.S_ISSOCK(args.socket.lstat().st_mode):
                args.socket.unlink()
        except FileNotFoundError:
            pass
    return 0
