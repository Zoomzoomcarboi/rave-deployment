# Gate 2B network and engineering SSH acceptance

This procedure qualifies only the RAVE OS Gate 2B networking, management AP, DHCP,
web-listener, and non-publishable engineering SSH architecture. It does not qualify
the complete RAVE system for production or road use.

## Evidence boundary

The `gate2b-ethernet-ssh-4c4bb1a` debug image exposed three proven management defects:
NetworkManager 1.52.1 rejected a literal empty `gateway=`, dnsmasq 2.91 rejected
`log-dhcp=0`, and `ProtectSystem=strict` prevented dnsmasq from writing its lease
database. Live, narrow corrections established a working AP, client DHCP, management
web UI, and concurrent Ethernet SSH.

After all three live corrections, one reboot retained Ethernet and the management
stack but lost the TCP/22 listener. `BindToDevice=eth0` is the high-confidence cause:
systemd documents that it adds `BindsTo=` and `After=` relationships to the interface
device unit, and the observed good boot showed that relationship. The failed-boot
journal event that would prove the exact device-unit transition was not captured.

The current source removes that lifetime coupling. It is not hardware-validated until
a newly built, untouched image passes this procedure.

## Qualification artifact

Build with the repository entry point and preserve these records beside the artifact:

- repository commit and dirty-worktree state from `provenance.json`;
- rpi-image-gen tag and commit;
- `artifact-verification.json`;
- compressed-image path, byte size, and SHA-256;
- exact flashed-media identity;
- Pi model/revision and Ethernet/Wi-Fi hardware identity;
- qualification date and operator.

The build must succeed through the target image's own `dnsmasq --test` and
`systemd-analyze verify` gates. Do not edit the image, boot partition, or rootfs after
the build. Flash the recorded artifact to clean supported media without Raspberry Pi
Imager customizations.

## Test topology

```text
ZBook eth0 10.77.0.3/24 ---- RAVE Pi eth0 10.77.0.1/24 ---- Comma 10.77.0.2/24

phone/laptop Wi-Fi client ---- RAVE-Setup ---- RAVE Pi wlan0 192.168.77.1/24
```

The ZBook Ethernet profile must have no gateway or DNS. Remove or disable any other
host route that could make a negative exposure check ambiguous.

## Five consecutive cold boots

Perform at least five consecutive cold boots from the same untouched flashed image.
For each cycle, remove Pi power after an orderly shutdown, wait for power loss to be
complete, restore power, and do not restart or repair any RAVE service. Record one row:

| Boot | boot ID | eth ping | SSH/auth | AP | DHCP address | web | unit checks | result |
|---:|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |
| 4 | | | | | | | | |
| 5 | | | | | | | | |

On the engineering ZBook, run these checks after every boot:

```sh
ping -c 10 10.77.0.1
nc -vz -w 3 10.77.0.1 22
ssh -o BatchMode=yes -o ConnectTimeout=5 pi@10.77.0.1 'printf "SSH_AUTH_OK\\n"'
curl --interface 10.77.0.3 --connect-timeout 3 --max-time 5 http://10.77.0.1:8080/
ssh -o BatchMode=yes pi@10.77.0.1 'cat /proc/sys/kernel/random/boot_id'
ssh -o BatchMode=yes pi@10.77.0.1 'sudo -n bash -s' < scripts/validate-gate2b-network.sh
```

Expected: ping has 0% packet loss, TCP/22 and key authentication succeed, and the
Ethernet request to port 8080 fails. The target-local script must pass without changing
service state. It explicitly inspects each RAVE unit; `systemctl --failed` alone is not
accepted as health evidence because a permanently failing service may be in
`activating (auto-restart)`.

From the management Wi-Fi client after every boot:

1. Confirm `RAVE-Setup` appeared without intervention.
2. Join it and record the leased address; it must be within `192.168.77.100-199`.
3. Load `http://192.168.77.1:8080`.
4. Confirm TCP `192.168.77.1:22` is refused or closed.
5. Confirm the client received no default gateway and no DNS server from RAVE.

At least once during the five-boot run, retain evidence of a real DHCPACK and the
lease database:

```sh
ssh -o BatchMode=yes pi@10.77.0.1 'sudo -n journalctl -b -u rave-management-dhcp.service --no-pager | grep DHCPACK'
ssh -o BatchMode=yes pi@10.77.0.1 'sudo -n stat /var/lib/misc/dnsmasq.leases'
```

At least once, retain the effective SSH relationships:

```sh
ssh -o BatchMode=yes pi@10.77.0.1 'systemctl show ssh.socket -p ActiveState -p SubState -p Listen -p FreeBind -p BindToDevice -p BindsTo -p BoundBy -p After -p Requires'
```

`BindsTo=` must not contain `sys-subsystem-net-devices-eth0.device`; the effective
listener must remain exactly `10.77.0.1:22`. Host keys must be absent from the generic
rootfs, present after first boot, stable across these reboots on one Pi, and different
from a separately flashed device's keys.

## Isolation and robustness after the five-boot pass

Only after all five normal boots pass, perform these controlled tests. Do not restart
`ssh.socket` to recover a failure.

1. Disconnect and reconnect the Ethernet cable. Wi-Fi/DHCP/web must remain healthy,
   and SSH must return when link connectivity returns without a socket restart.
2. Disconnect, reconnect, and renew the management client. Ethernet/SSH must remain
   healthy and DHCP/web must recover normally.
3. Exercise the web UI while maintaining an authenticated Ethernet SSH session. The
   SSH listener and session must remain healthy.
4. From Ethernet SSH, restart NetworkManager once. Ethernet ping and SSH must remain
   healthy while the management AP goes down and returns.
5. Restart `rave-management-dhcp.service` once. Ethernet ping and SSH must remain
   healthy; a management client must subsequently renew a lease.
6. Stop `rave-webd.service` briefly and confirm Ethernet/SSH and DHCP remain healthy;
   start it and confirm only the management listener returns.

Record explicit `ActiveState`, `SubState`, and `Result` for every RAVE unit after each
fault test. Any need to edit configuration, add a route, restart SSH, or repair the
target invalidates the run.

## Pass boundary

Passing this procedure supports the claim that the named clean image is
hardware-validated for the Gate 2B network/SSH matrix on the named hardware. It does
not qualify secure provisioning, the currently open AP, perception, Hailo, transport
authentication, thermal/power behavior, updates, vehicle integration, or complete RAVE
release readiness.
