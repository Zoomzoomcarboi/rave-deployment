# Management network architecture (Gate 2B candidate)

Gate 2B installs one product-owned open `RAVE-Setup` NetworkManager AP profile on
`wlan0`. It uses `192.168.77.1/24`, no gateway/default route, disabled IPv6, and a
bounded dnsmasq DHCP scope of `192.168.77.100-192.168.77.199`. IPv4/IPv6 forwarding,
bridging, NAT, DNS forwarding, and Internet sharing are forbidden.

The NetworkManager keyfile intentionally omits the `ipv4.gateway` property. A literal
empty `gateway=` is not equivalent on the validated target stack: NetworkManager
1.52.1 rejects that keyfile as invalid. The image build statically enforces this source
contract; loading and automatically activating the profile remains part of clean-image
Pi validation.

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

The management DHCP service uses dnsmasq with DNS disabled, no advertised router, no
advertised DNS server, and sockets restricted to `wlan0`. `ProtectSystem=strict`
remains enabled. Its only writable filesystem exception is `/var/lib/misc`, matching
the explicit `/var/lib/misc/dnsmasq.leases` database. The generic image carries no
lease state. The target image's dnsmasq parser runs during the build before artifact
verification is allowed to pass.

`Restart=on-failure` with a bounded five-second delay is retained for recoverable
runtime failures. Permanent source syntax errors are build blockers, so retry policy
is not used to conceal malformed shipped configuration.

The open AP is permitted only for Gate 2B prerelease hardware validation. Secure,
per-device onboarding remains mandatory before production/public release qualification.

## Runtime-link isolation

Dedicated Ethernet remains Pi `10.77.0.1/24`, Comma `10.77.0.2/24`, with no gateway,
DNS, default route, or bridge to management Wi-Fi. Runtime must work without Wi-Fi, and
the management web UI must not listen on the Comma-facing address by default.

For the non-publishable Gate 2B engineering image, the ZBook uses `10.77.0.3/24` and
SSH is socket-activated only at `10.77.0.1:22`. `FreeBind=yes` permits deterministic
early binding to that exact address. `BindToDevice=eth0` is intentionally absent:
systemd turns that setting into a device-unit `BindsTo=` lifetime relationship, which
can stop the listener if the device unit transiently disappears even after Ethernet
configuration returns. Exact-address binding already excludes `192.168.77.1:22`.

SSH and its unconditional, idempotent per-device host-key generator have no dependency
on NetworkManager, Wi-Fi initialization, DHCP, web management, or network-online. The
RAVE generator is the socket's sole host-key prerequisite; a second conditional
first-boot generator is not scheduled with it. The engineering image remains key-only,
disallows root/password/keyboard-interactive authentication, carries only the reviewed
public authorization key, and is not a publishable image policy.

Clean-image qualification follows [GATE2B_NETWORK_ACCEPTANCE.md](GATE2B_NETWORK_ACCEPTANCE.md),
including five consecutive untouched cold boots and controlled subsystem fault tests.
