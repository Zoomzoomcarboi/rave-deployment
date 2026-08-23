# Management network architecture (Gate 1)

Gate 1 defines state and service boundaries only. It does not change host networking,
create an AP, call `nmcli`, use NetworkManager D-Bus, or store credentials.

```text
boot -> try saved management Wi-Fi
     -> connected: user LAN plus reviewed local discovery
     -> no usable network / bounded timeout: transition to provisioning AP
     -> user requests station connection through typed backend API
     -> success: station-connected
     -> bounded failure: recover provisioning AP
```

`rave_web.network_policy` models these transitions as pure logic. Timeouts belong to a
future privileged service and must be monotonic, bounded, and independently supervised.

## Privilege boundary

`rave-webd` remains unprivileged and read-mostly. A future `rave-networkd` may own only
the narrow operations required to scan, attempt a station connection, forget a saved
management network, and start/stop a provisioning AP. Its IPC must be typed, bounded,
locally authenticated, and never return stored credentials. It must not accept arbitrary
shell commands, paths, NetworkManager properties, or D-Bus calls from the browser.

The web listener requires a reviewed management-interface binding strategy before
deployment. Gate 1 binds loopback only, avoiding accidental exposure while that policy
is unresolved.

## Runtime-link isolation

Dedicated Ethernet remains Pi `10.77.0.1/24`, Comma `10.77.0.2/24`, with no gateway,
DNS, default route, or bridge to management Wi-Fi. Runtime must work without Wi-Fi, and
the management web UI must not listen on the Comma-facing address by default.
