# Management network architecture

This document describes the implemented, host-tested management-network candidate.
The station transition and recovery path has not yet been validated on Raspberry Pi
hardware.

## Network roles

NetworkManager supplies the `wlan0` device API, while `rave-networkd` is the sole
profile-activation owner. Both the saved `RAVE-Management` station profile and the
`RAVE-Setup` AP profile use `autoconnect=false`. At daemon startup, `rave-networkd`
explicitly tries the saved profile by UUID. If it is absent or cannot connect within
the bounded NetworkManager activation window, the daemon activates the product-owned
open `RAVE-Setup` profile and starts the bounded DHCP service.

`RAVE-Setup` uses `192.168.77.1/24`, no gateway/default route, disabled IPv6, and a
dnsmasq lease scope of `192.168.77.100-192.168.77.199`. DNS service, advertised router
and DNS options, IPv4/IPv6 forwarding, bridging, NAT, and Internet sharing are
forbidden. NetworkManager does not independently activate either RAVE profile.

The NetworkManager keyfile intentionally omits the `ipv4.gateway` property. A literal
empty `gateway=` is not equivalent on the validated target stack: NetworkManager
1.52.1 rejects that keyfile as invalid.

```text
boot -> try RAVE-Management
     -> usable saved profile: station-connected
     -> absent/failure/timeout: transition -> verified RAVE-Setup + DHCP

provisioning UI -> scan -> selected SSID + optional password
                -> transition -> staged RAVE-Management-Pending profile
                -> success: verify new profile, retire prior UUID, station-connected
                -> failure: retain/restore prior UUID, delete candidate, restore AP + DHCP
```

Profile promotion is UUID-addressed and rollback-safe. The prior canonical profile is
left untouched while the activated candidate is renamed to `RAVE-Management` and its
`autoconnect=false` policy is verified. Only then is the prior UUID renamed to the
noncanonical `RAVE-Management-Previous` backup identity and deleted. A failure before
that final deletion demotes/removes the candidate and restores the prior UUID to the
canonical identity. Boot recovery also recognizes the backup identity if an interrupted
rollback could not restore its name.

The controller retains the existing explicit `NetworkMode`/`NetworkEvent` state model.
A mode does not become `PROVISIONING_AP` until both AP activation and DHCP startup
succeed. Work is held in a one-item queue, command timeouts are bounded, and overlapping
state-changing requests are rejected without leaving hidden queued work. An idle
ten-second reconciliation check restores the AP if an established station or AP later
disappears.

## Privilege boundary and credential flow

```text
browser
  -> strict FastAPI request
  -> rave-webd (User=rave, Group=rave, NoNewPrivileges=true)
  -> /run/rave/networkd.sock (root:rave, 0660, peer UID checked)
  -> rave-networkd (root, empty capability set, strict sandbox, core dumps disabled)
  -> fixed NetworkManager/systemd operations for wlan0 only
```

The versioned local protocol supports only `status`, `scan`, `connect`, and
`provisioning`. Exact request fields are enforced. It has no command, argv, interface,
path, D-Bus method, or NetworkManager-property input. The client verifies that the
server peer is root; the server verifies that the client peer is the `rave` UID.
Requests and responses have fixed byte limits.

For a protected network, the password flows from the browser request through the
unprivileged process and typed local request into the one pending controller work item.
`rave-networkd` supplies it to `nmcli` through an anonymous `memfd` password file. It
never appears in `nmcli` arguments, logs, status, scan results, API responses, or image
provenance. Python cannot guarantee in-place erasure of immutable strings, so the code
instead avoids persistence and releases references after the bounded transition.

The current version supports open networks and WPA/WPA2/WPA3 personal networks.
Enterprise and unsupported security modes are reported but not actuated.

## Web listener and DHCP ownership

`rave-webd.socket` owns port 8080 with `BindToDevice=wlan0`; `rave-webd` consumes only
the inherited descriptor. The service itself is restricted to creating `AF_UNIX`
sockets, so it cannot create another IPv4/IPv6 listener or outbound runtime-Ethernet
connection. It remains independent of perception and is socket-activated whether
`wlan0` is in station or AP mode.

The DHCP service is not enabled directly at boot. `rave-networkd` starts it only after
the AP is active and stops it before a station attempt. dnsmasq has DNS disabled, does
not advertise a router or DNS server, and is restricted to `wlan0`. Its only writable
filesystem exception is `/var/lib/misc`, which owns the bounded lease database.

The open AP is permitted only for prerelease hardware validation. Per-device secure
bootstrap and management authentication remain release blockers.

## Timekeeping

The image timezone is `Etc/UTC`. The API reports the current UTC wall clock, whether
systemd currently marks it synchronized, and whether an RTC device exists. It never
turns RTC presence into a synchronization claim. systemd-timesyncd retains its
last-known-clock state in the image/persistent filesystem and can synchronize normally
after station mode obtains an upstream route. No clock-setting HTTP operation exists.
The provisioning AP and dedicated Ethernet gain no gateway for NTP.

## Runtime-link and SSH isolation

Dedicated Ethernet remains Pi `10.77.0.1/24`, Comma `10.77.0.2/24`, and optionally an
engineering host at `10.77.0.3/24`. It has no gateway, DNS, default route, forwarding,
NAT, bridge, or web listener. NetworkManager is explicitly forbidden from owning
`eth0`; systemd-networkd applies the fixed connected-only policy. Perception and future
runtime transport do not depend on Wi-Fi.

The non-publishable engineering image exposes key-only SSH only at `10.77.0.1:22`.
The repository contains no default developer authorization key. Each engineering build
must receive one validated OpenSSH ED25519 public key; the image verifier checks its
mode/ownership and provenance records its public fingerprint. SSH has no dependency on
NetworkManager, `rave-networkd`, DHCP, web management, or network-online.

Clean-image qualification follows
[GATE2B_NETWORK_ACCEPTANCE.md](GATE2B_NETWORK_ACCEPTANCE.md). Static checks and host
tests establish implementation/unit-test status only; they do not establish Pi or
hardware validation.
