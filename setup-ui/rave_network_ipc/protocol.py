"""Small, versioned wire contract shared by rave-webd and rave-networkd."""

from enum import StrEnum

API_VERSION = "v1"
SOCKET_PATH = "/run/rave/networkd.sock"
MAX_REQUEST_BYTES = 2048
MAX_RESPONSE_BYTES = 64 * 1024
MAX_NETWORKS = 64
SSID_MAX_BYTES = 32
PASSWORD_MIN_BYTES = 8
PASSWORD_MAX_BYTES = 63


class NetworkMode(StrEnum):
    UNCONFIGURED = "unconfigured"
    STATION_CONNECTING = "station_connecting"
    STATION_CONNECTED = "station_connected"
    PROVISIONING_AP = "provisioning_ap"
    TRANSITION = "transition"
    ERROR = "error"


class NetworkAction(StrEnum):
    STATUS = "status"
    SCAN = "scan"
    CONNECT = "connect"
    PROVISIONING = "provisioning"


class WifiSecurity(StrEnum):
    OPEN = "open"
    WPA_PERSONAL = "wpa_personal"
    ENTERPRISE = "enterprise"
    UNSUPPORTED = "unsupported"


def validate_ssid(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("ssid_invalid")
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > SSID_MAX_BYTES:
        raise ValueError("ssid_length_invalid")
    if any(character == "\x00" or character in "\r\n" for character in value):
        raise ValueError("ssid_contains_control_character")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError("ssid_contains_control_character")
    return value


def validate_password(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("password_invalid")
    encoded = value.encode("utf-8")
    if not PASSWORD_MIN_BYTES <= len(encoded) <= PASSWORD_MAX_BYTES:
        raise ValueError("password_length_invalid")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError("password_contains_control_character")
    return value
