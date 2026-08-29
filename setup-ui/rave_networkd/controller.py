"""Explicit management-network state transitions and bounded recovery policy."""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from rave_network_ipc.protocol import NetworkMode
from rave_network_ipc.state import NetworkEvent, transition

from .backend import AccessPoint

LOGGER = logging.getLogger("rave-networkd")


class NetworkBackend(Protocol):
    def has_saved_station(self) -> bool: ...

    def activate_saved_station(self) -> tuple[bool, str | None, str | None]: ...

    def connect_station(
        self, ssid: str, password: str | None
    ) -> tuple[bool, str | None, str | None]: ...

    def activate_provisioning(self) -> tuple[bool, str | None]: ...

    def scan(self) -> list[AccessPoint]: ...

    def active_station_ssid(self) -> str | None: ...

    def provisioning_ready(self) -> bool: ...


@dataclass(frozen=True)
class NetworkSnapshot:
    mode: NetworkMode
    provisioning_ap_active: bool
    station_ssid: str | None
    last_error: str | None


class WorkKind(StrEnum):
    BOOT = "boot"
    CONNECT = "connect"
    PROVISIONING = "provisioning"


@dataclass(frozen=True)
class WorkItem:
    kind: WorkKind
    ssid: str | None = None
    password: str | None = None


class NetworkController:
    def __init__(self, backend: NetworkBackend) -> None:
        self._backend = backend
        self._mode = NetworkMode.UNCONFIGURED
        self._station_ssid: str | None = None
        self._last_error: str | None = None
        self._lock = threading.Lock()
        self._operation_lock = threading.Lock()
        self._work: queue.Queue[WorkItem] = queue.Queue(maxsize=1)

    def snapshot(self) -> NetworkSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def scan(self) -> list[AccessPoint]:
        with self._lock:
            if self._mode not in {
                NetworkMode.PROVISIONING_AP,
                NetworkMode.STATION_CONNECTED,
            }:
                raise RuntimeError("network_transition_busy")
        with self._operation_lock:
            return self._backend.scan()

    def request_boot(self) -> NetworkSnapshot:
        with self._lock:
            self._enqueue_transition_locked(WorkItem(WorkKind.BOOT), NetworkEvent.BOOT)
            return self._snapshot_locked()

    def request_connect(self, ssid: str, password: str | None) -> NetworkSnapshot:
        with self._lock:
            self._enqueue_transition_locked(
                WorkItem(WorkKind.CONNECT, ssid, password),
                NetworkEvent.STATION_REQUESTED,
            )
            self._last_error = None
            return self._snapshot_locked()

    def request_provisioning(self) -> NetworkSnapshot:
        with self._lock:
            if self._mode == NetworkMode.PROVISIONING_AP:
                return self._snapshot_locked()
            self._enqueue_transition_locked(
                WorkItem(WorkKind.PROVISIONING),
                NetworkEvent.PROVISIONING_REQUESTED,
            )
            self._last_error = None
            return self._snapshot_locked()

    def process_next(self, timeout: float | None = None) -> bool:
        try:
            item = self._work.get(timeout=timeout)
        except queue.Empty:
            return False
        try:
            with self._operation_lock:
                if item.kind == WorkKind.BOOT:
                    self._process_boot()
                elif item.kind == WorkKind.CONNECT:
                    assert item.ssid is not None
                    self._process_connect(item.ssid, item.password)
                else:
                    self._restore_provisioning(None)
        except (OSError, RuntimeError, ValueError):
            self._recover_unexpected_failure()
            raise
        finally:
            self._work.task_done()
        return True

    def reconcile(self) -> None:
        mode = self.snapshot().mode
        with self._operation_lock:
            if mode == NetworkMode.STATION_CONNECTED:
                self._reconcile_station()
            elif mode == NetworkMode.PROVISIONING_AP:
                self._reconcile_provisioning()

    def _process_boot(self) -> None:
        if not self._backend.has_saved_station():
            self._apply(NetworkEvent.NO_SAVED_NETWORK)
            self._restore_provisioning(None)
            return
        success, ssid, error = self._backend.activate_saved_station()
        if success:
            self._station_connected(ssid)
            return
        self._apply(NetworkEvent.STATION_TIMEOUT)
        self._restore_provisioning(error or "saved_station_timeout")

    def _process_connect(self, ssid: str, password: str | None) -> None:
        success, connected_ssid, error = self._backend.connect_station(ssid, password)
        if success:
            self._station_connected(connected_ssid)
            return
        self._apply(NetworkEvent.STATION_TIMEOUT)
        self._restore_provisioning(error or "station_timeout")

    def _station_connected(self, ssid: str | None) -> None:
        with self._lock:
            self._apply_locked(NetworkEvent.STATION_CONNECTED)
            self._station_ssid = ssid
            self._last_error = None
        LOGGER.info("management Wi-Fi entered station-connected mode")

    def _restore_provisioning(self, prior_error: str | None) -> None:
        try:
            success, ap_error = self._backend.activate_provisioning()
        except (OSError, RuntimeError, ValueError):
            success, ap_error = False, "ap_activation_failed"
        with self._lock:
            if success:
                self._apply_locked(NetworkEvent.AP_READY)
                self._station_ssid = None
                self._last_error = prior_error
            else:
                self._apply_locked(NetworkEvent.AP_FAILED)
                self._station_ssid = None
                self._last_error = ap_error or "ap_activation_failed"
        if success:
            LOGGER.info("management Wi-Fi entered provisioning-AP mode")
        else:
            LOGGER.error("management Wi-Fi provisioning AP recovery failed")

    def _reconcile_station(self) -> None:
        try:
            ssid = self._backend.active_station_ssid()
        except (OSError, RuntimeError, ValueError):
            ssid = None
        with self._lock:
            if self._mode != NetworkMode.STATION_CONNECTED:
                return
            if ssid is not None:
                self._station_ssid = ssid
                return
            self._apply_locked(NetworkEvent.STATION_TIMEOUT)
        self._restore_provisioning("station_connection_lost")

    def _reconcile_provisioning(self) -> None:
        try:
            ready = self._backend.provisioning_ready()
        except (OSError, RuntimeError, ValueError):
            ready = False
        if ready:
            return
        with self._lock:
            if self._mode != NetworkMode.PROVISIONING_AP:
                return
            self._apply_locked(NetworkEvent.PROVISIONING_REQUESTED)
        self._restore_provisioning("provisioning_ap_lost")

    def _recover_unexpected_failure(self) -> None:
        with self._lock:
            if self._mode == NetworkMode.STATION_CONNECTING:
                self._apply_locked(NetworkEvent.STATION_TIMEOUT)
            elif self._mode != NetworkMode.TRANSITION:
                self._mode = NetworkMode.ERROR
                self._station_ssid = None
                self._last_error = "network_operation_failed"
                return
        self._restore_provisioning("network_operation_failed")

    def _apply(self, event: NetworkEvent) -> None:
        with self._lock:
            self._apply_locked(event)

    def _apply_locked(self, event: NetworkEvent) -> None:
        self._mode = transition(self._mode, event)

    def _enqueue_locked(self, item: WorkItem) -> None:
        try:
            self._work.put_nowait(item)
        except queue.Full as error:
            raise RuntimeError("network_transition_busy") from error

    def _enqueue_transition_locked(self, item: WorkItem, event: NetworkEvent) -> None:
        next_mode = transition(self._mode, event)
        self._enqueue_locked(item)
        self._mode = next_mode

    def _snapshot_locked(self) -> NetworkSnapshot:
        return NetworkSnapshot(
            mode=self._mode,
            provisioning_ap_active=self._mode == NetworkMode.PROVISIONING_AP,
            station_ssid=self._station_ssid,
            last_error=self._last_error,
        )
