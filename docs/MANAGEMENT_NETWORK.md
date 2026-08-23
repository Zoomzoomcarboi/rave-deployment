# Management network architecture (Gate 2B candidate)

Gate 2B installs one product-owned open `RAVE-Setup` NetworkManager AP profile on
`wlan0`. It uses `192.168.77.1/24`, no gateway/default route, disabled IPv6, and a
bounded dnsmasq DHCP scope of `192.168.77.100-192.168.77.199`. IPv4/IPv6 forwarding,
bridging, NAT, DNS forwarding, and Internet sharing are forbidden.

```text
boot -> try saved management Wi-Fi
     -> connected: user LAN plus reviewed local discovery
     -> no usable network / bounded timeout: transition to provisioning AP
     -> user requests station connection through typed backend API
     -> success: station-connected
     -> bounded failure: recover provisioning AP
```

Gate 2B implements only the deterministic first-boot AP portion of this future flow.
Station scanning and credential-based transition are not integrated yet.

## Privilege boundary

`rave-webd` remains unprivileged and read-mostly. A future `rave-networkd` may own only
the narrow operations required to scan, attempt a station connection, forget a saved
management network, and start/stop a provisioning AP. Its IPC must be typed, bounded,
locally authenticated, and never return stored credentials. It must not accept arbitrary
shell commands, paths, NetworkManager properties, or D-Bus calls from the browser.

The web listener is bound only to `192.168.77.1:8080`; it never binds the wildcard or
the dedicated Ethernet address. The installed service explicitly selects the Pi
read-only provider with `RAVE_PROVIDER=pi` and remains `User=rave`, `Group=rave`.

The open AP is permitted only for Gate 2B prerelease hardware validation. Secure,
per-device onboarding remains mandatory before production/public release qualification.

## Runtime-link isolation

Dedicated Ethernet remains Pi `10.77.0.1/24`, Comma `10.77.0.2/24`, with no gateway,
DNS, default route, or bridge to management Wi-Fi. Runtime must work without Wi-Fi, and
the management web UI must not listen on the Comma-facing address by default.
