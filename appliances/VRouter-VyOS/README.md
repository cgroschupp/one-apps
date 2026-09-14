# one-vyos-vrouter

`one-vyos-vrouter` is a Python controller that ports the OpenNebula Virtual
Router appliance services to native VyOS 1.5 configuration. It reads
`/run/one-context/one_env`, bootstraps the local interfaces, polls OneGate, and
commits changes only when the desired configuration changes.

Implemented feature mappings:

- OpenNebula NIC addresses, VIPs, MTUs, gateways, and management NIC exclusion
- Router4 through native VyOS IPv4 forwarding nodes
- NAT4 masquerade and destination port forwarding
- SDNAT4 from OneGate VNET lease information
- Keepalived semantics through native VyOS VRRP and sync groups
- DHCP4v2 through the native Kea DHCP server
- DNS recursion, forwarding, ACLs, and endpoint records
- LVS through native VyOS IPVS virtual servers
- HAProxy through native `load-balancing haproxy` configuration
- WireGuard with persistent key material and OneGate publication

## Polling and failure behavior

The service runs continuously and requests `/vrouter?extended=true` from
`ONEGATE_ENDPOINT` every 30 seconds. It follows VRouter network IDs through
`/vnet/<id>` and reads member VMs through `/vms/<id>` for dynamic NAT,
load-balancer, and WireGuard data.

Set `ONEAPP_VNF_VYOS_REFRESH_RATE` to change the interval. Failed polls use an
exponential backoff capped at 300 seconds. The last successful response is
stored in `/config/one-vyos-vrouter/onegate.json` and remains active while
OneGate is unavailable.

The applied-command state is kept under `/run/one-vyos-vrouter`, so every boot
reapplies the context even when runtime changes were intentionally not saved.

OneGate uses the normal VyOS routing table. The management interface is
identified by `ETH<N>_VROUTER_MANAGEMENT=YES` and is excluded from forwarding,
NAT, DHCP, DNS, VRRP, VPN endpoints, and load-balancer data paths.

TLS verification is disabled by default for compatibility with appliance
self-signed certificates. Set `ONEAPP_VNF_VYOS_ONEGATE_TLS_VERIFY=YES` to
require certificate verification.

## Running

Inspect one reconciliation without changing VyOS:

```sh
/usr/sbin/one-vyos-vrouter --dry-run --no-onegate
```

Run one live reconciliation:

```sh
/usr/sbin/one-vyos-vrouter --once
```

The default service mode keeps polling until systemd stops it. `--save` also
saves commits into `/config/config.boot`; by default the context remains the
source of truth and every boot performs a fresh reconciliation.

## Building

```sh
make test
make deb
```

The resulting package is written to
`out/one-vyos-vrouter_0.2.0-1_all.deb`. For a persistent production appliance,
include this package in the VyOS image build as a custom Debian package.

For a live test installation:

```sh
sudo dpkg -i out/one-vyos-vrouter_0.2.0-1_all.deb
sudo systemctl start one-vyos-vrouter.service
sudo journalctl -u one-vyos-vrouter.service -f
```

## Compatibility notes

The primary target is VyOS 1.5 and Python 3.9 or newer. Set
`ONEAPP_VNF_VYOS_VERSION=1.4` to render the older DHCP option paths. VyOS 1.4
uses `load-balancing reverse-proxy` instead of the 1.5 HAProxy tree, so native
HAProxy rendering requires VyOS 1.5.

The CoreDHCP `MAC2IP` plugin has no exact native Kea equivalent. DHCP ranges,
gateway/DNS options, lease times, router/VIP exclusions, and explicit ranges
are implemented; deterministic lease selection from only a MAC prefix is not.
