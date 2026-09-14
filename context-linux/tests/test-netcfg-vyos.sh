#!/usr/bin/env bash
# shellcheck disable=SC1091
set -eo pipefail

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
TEST_DIR=$(mktemp -d)
trap 'rm -rf "${TEST_DIR}"' EXIT

mkdir -p "${TEST_DIR}/bin" "${TEST_DIR}/state" "${TEST_DIR}/run"

cat >"${TEST_DIR}/bin/ip" <<'EOF'
#!/bin/sh
cat <<'OUT'
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    link/ether 02:00:c0:00:02:0a brd ff:ff:ff:ff:ff:ff
OUT
EOF

cat >"${TEST_DIR}/bin/sg" <<'EOF'
#!/bin/sh
cp "$3" "${VYOS_TEST_CAPTURE}"
EOF
chmod 0755 "${TEST_DIR}/bin/ip" "${TEST_DIR}/bin/sg"

export PATH="${TEST_DIR}/bin:${PATH}"
export VYOS_TEST_CAPTURE="${TEST_DIR}/applied.vbash"
export VYOS_CONTEXT_STATE_DIR="${TEST_DIR}/state"
export VYOS_CONTEXT_STATE="${TEST_DIR}/state/network.commands"
export VYOS_CONTEXT_PENDING="${TEST_DIR}/run/network.commands"

export ETH0_MAC='02:00:c0:00:02:0a'
export ETH0_METHOD='static'
export ETH0_IP='192.0.2.10'
export ETH0_NETWORK='192.0.2.0'
export ETH0_MASK='255.255.255.0'
export ETH0_GATEWAY='192.0.2.1'
export ETH0_METRIC='20'
export ETH0_MTU='1450'
export ETH0_DNS='192.0.2.53 2001:db8::53'
export ETH0_SEARCH_DOMAIN='example.test'
export ETH0_ROUTES='198.51.100.0/24 via 192.0.2.2'
export ETH0_IP6='2001:db8::10'
export ETH0_IP6_PREFIX_LENGTH='64'
export ETH0_IP6_GATEWAY='2001:db8::1'
export SET_HOSTNAME='router.example.test'
export ONEGATE_ENDPOINT='http://169.254.16.9:5030'

# shellcheck source=../src/etc/one-context.d/loc-10-network.d/functions
. "${ROOT}/src/etc/one-context.d/loc-10-network.d/functions"
# shellcheck source=/dev/null
. "${ROOT}/src/etc/one-context.d/loc-10-network.d/netcfg-vyos##vyos"

initialize_network
configure_network

grep -Fq $'delete interfaces ethernet eth0 address 192.0.2.10/24\tset interfaces ethernet eth0 address 192.0.2.10/24' "${VYOS_CONTEXT_STATE}"
grep -Fq $'delete interfaces ethernet eth0 mtu\tset interfaces ethernet eth0 mtu 1450' "${VYOS_CONTEXT_STATE}"
grep -Fq $'delete protocols static route 198.51.100.0/24 next-hop 192.0.2.2\tset protocols static route 198.51.100.0/24 next-hop 192.0.2.2' "${VYOS_CONTEXT_STATE}"
grep -Fq $'delete protocols static route 169.254.16.9/32 interface eth0\tset protocols static route 169.254.16.9/32 interface eth0' "${VYOS_CONTEXT_STATE}"
grep -Fq $'delete system name-server 2001:db8::53\tset system name-server 2001:db8::53' "${VYOS_CONTEXT_STATE}"
grep -Fq $'delete system domain-name\tset system domain-name example.test' "${VYOS_CONTEXT_STATE}"
grep -Fq "commit comment 'OpenNebula context network' || exit 1" "${VYOS_TEST_CAPTURE}"
grep -Fq 'save || exit 1' "${VYOS_TEST_CAPTURE}"

unset ETH0_ROUTES ETH0_DNS ETH0_SEARCH_DOMAIN
configure_network

grep -Fq 'delete protocols static route 198.51.100.0/24 next-hop 192.0.2.2 || true' "${VYOS_TEST_CAPTURE}"
grep -Fq 'delete system name-server 192.0.2.53 || true' "${VYOS_TEST_CAPTURE}"
if grep -Fq $'\tset protocols static route 198.51.100.0/24' "${VYOS_CONTEXT_STATE}"; then
    echo 'removed route remains in desired state' >&2
    exit 1
fi

echo 'VyOS network backend test passed'
