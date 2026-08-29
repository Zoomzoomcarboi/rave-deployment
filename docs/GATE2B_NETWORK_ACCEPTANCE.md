# Management network and engineering SSH acceptance

This procedure qualifies only the named RAVE OS image's management Wi-Fi, AP recovery,
DHCP, web-listener, UTC/time reporting, runtime-Ethernet isolation, and non-publishable
engineering SSH architecture. It does not qualify perception, Hailo runtime, the Comma
link, production security, or road use.

## Evidence boundary

The currently powered Pi has hardware-validated the AP-only predecessor: fixed runtime
Ethernet, isolated `RAVE-Setup`, bounded DHCP, management-only HTTP, address-scoped
key-only SSH, healthy storage/thermals, and truthful not-integrated markers. Its
manually appended engineering key and temporary console password are diagnostic state,
not source or image policy.

The current source replaces the baked authorization key, adds `rave-networkd` and
station provisioning, changes the web listener to a `wlan0`-bound systemd socket, and
sets UTC/time reporting. Those changes are implemented and host-tested only until a
fresh untouched image passes this procedure.

## Qualification artifact

Build with one explicitly selected public key:

```sh
RAVE_ENGINEERING_SSH_PUBLIC_KEY_FILE=/path/to/engineering-key.pub \
  ./scripts/build-rave-os.sh
```

Preserve the following beside the artifact:

- repository commit and dirty-worktree state from `provenance.json`;
- rpi-image-gen tag/commit and builder-container digest;
- engineering public-key fingerprint;
- `artifact-verification.json`;
- image path, byte size, and SHA-256;
- flashed-media identity, Pi model/revision, and network hardware identity;
- qualification date and operator.

The build must pass the target image's dnsmasq and systemd parsers and the artifact
verifier. Do not customize the image with Raspberry Pi Imager, edit the rootfs, append
keys, set a console password, or repair services after flashing.

## Test topology

```text
engineering host 10.77.0.3/24 ---- RAVE Pi eth0 10.77.0.1/24

management client ---- RAVE-Setup ---- RAVE Pi wlan0 192.168.77.1/24

controlled management LAN/AP ---- RAVE Pi wlan0 via RAVE-Management
```

The engineering-host Ethernet profile has no gateway or DNS. The controlled management
LAN should provide ordinary DHCP/default-route service; provide upstream NTP reachability
for the time-synchronization test. Remove other host routes that would make negative
exposure checks ambiguous. Camera and Comma hardware are not required for this
management-only qualification and their absence is not a failure.

## Five consecutive cold boots from an untouched AP-fallback image

Use a fresh image with no saved `RAVE-Management` profile. Perform five cold boots from
the same untouched media. After orderly shutdown, remove power completely before each
restart. Do not restart or repair any RAVE service.

For every boot, record boot ID, runtime ping, SSH/authentication, AP visibility, DHCP
lease, web response, RAVE unit states/results/restart counts, UTC timezone, synchronization
state, RTC presence, and result.

From the engineering host:

```sh
ping -c 10 10.77.0.1
nc -vz -w 3 10.77.0.1 22
ssh -o BatchMode=yes -o ConnectTimeout=5 pi@10.77.0.1 'printf "SSH_AUTH_OK\n"'
curl --interface 10.77.0.3 --connect-timeout 3 --max-time 5 http://10.77.0.1:8080/
ssh -o BatchMode=yes pi@10.77.0.1 'cat /proc/sys/kernel/random/boot_id'
ssh -o BatchMode=yes pi@10.77.0.1 'sudo -n bash -s' < scripts/validate-gate2b-network.sh
```

Expected: runtime ping and exact-address SSH succeed; the Ethernet HTTP request fails;
the target-local read-only script passes. `rave-networkd` and `rave-webd.socket` are
healthy without restart loops. `rave-management-dhcp` is active only in AP mode.

From the management client after every boot:

1. Confirm `RAVE-Setup` appears after the bounded saved-network attempt.
2. Join it and receive exactly one address in `192.168.77.100-199`.
3. Load `http://192.168.77.1:8080` and verify all four page routes.
4. Confirm `192.168.77.1:22` is refused/closed.
5. Confirm RAVE advertises no default gateway and no DNS server.
6. Confirm the UI reports UTC and unsynchronized time honestly when no upstream exists.

Retain a real DHCPACK, lease-file metadata, effective socket policy, local IPC socket
ownership, SSH host-key fingerprints, and injected authorization-key fingerprint.
Host keys must persist across these boots and differ on a separately flashed device.
The effective SSH `BindsTo=` value must not contain
`sys-subsystem-net-devices-eth0.device`.

## Station transition and deterministic recovery

After the untouched AP boots pass:

1. Use the Network page to scan. Confirm results contain only SSID, signal, security,
   and connected state; no saved credential is returned.
2. Select the controlled management LAN and enter its credential. Confirm the warning
   appears before submitting and the UI does not claim success after HTTP disappears.
3. Confirm `RAVE-Setup` and its DHCP service stop, `RAVE-Management` becomes the sole
   saved station profile, and the Pi receives a normal LAN address/default route.
4. Confirm runtime Ethernet remains exactly `10.77.0.1/24`, unmanaged by NetworkManager,
   with no gateway, DNS, NAT, bridge, forwarding, or HTTP exposure.
5. Confirm the web UI is reachable only through `wlan0` using the station address.
   Record how the client rediscovers that address; local discovery is not implemented
   by the current image.
6. Confirm systemd-timesyncd can synchronize through the management LAN and the API
   exactly matches systemd's synchronization state. Connectivity alone is not a
   synchronization claim.
7. Reboot once and confirm the reviewed saved profile reconnects without exposing the
   AP.
8. Make the saved LAN unavailable and reboot. Confirm bounded automatic recovery to
   `RAVE-Setup` and DHCP without affecting runtime Ethernet or SSH.
9. From `RAVE-Setup`, submit a deliberately wrong credential. Confirm the request is
   bounded, the staged profile is removed, and `RAVE-Setup` returns automatically.
10. Deliberately request provisioning from station mode and confirm the same isolated
    AP contract returns.

Inspect the journal to confirm no supplied password appears. Search NetworkManager,
`rave-networkd`, `rave-webd`, and system logs using a unique non-secret test sentinel
embedded in a disposable test password; remove the disposable test LAN afterward.

## Fault containment

After the normal transitions pass, perform controlled service/interface fault tests:

- reconnect Ethernet while management remains healthy; SSH must return without a
  socket restart;
- restart NetworkManager once; runtime Ethernet and SSH must remain healthy, while
  `rave-networkd` restores a valid management mode;
- stop/start the web service; perception-independent networking and SSH remain healthy,
  and the socket reactivates only the web service;
- stop the DHCP service in AP mode; the daemon's bounded reconciliation must restore it;
- make the active station unavailable; the daemon must restore `RAVE-Setup`;
- terminate an HTTP client during a request; neither privileged daemon may enter a
  restart loop.

Record `ActiveState`, `SubState`, `Result`, and `NRestarts` after each test. Any manual
configuration edit, key append, gateway addition, bridge/NAT rule, or service repair
invalidates the qualification run.

## Pass boundary

Passing supports only a hardware-validated claim for the named image and this exact
management/SSH matrix. The open AP, lack of per-device management authentication,
absence of local discovery, redistribution review, Hailo/perception integration,
updates, vehicle integration, and complete RAVE system release gates remain unresolved.
