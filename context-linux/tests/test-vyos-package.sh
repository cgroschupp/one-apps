#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
PACKAGE=${1:-${ROOT}/out/one-context-vyos_7.4.0-0.deb}
TEST_DIR=$(mktemp -d)
trap 'rm -rf "${TEST_DIR}"' EXIT

ar -p "${PACKAGE}" data.tar.gz >"${TEST_DIR}/data.tar.gz"
tar -tzf "${TEST_DIR}/data.tar.gz" | sed -e 's#^\./##' -e '/^$/d' -e '/\/$/d' | sort >"${TEST_DIR}/actual"

cat >"${TEST_DIR}/expected" <<'EOF'
etc/one-context.d/loc-10-network
etc/one-context.d/loc-10-network.d/functions
etc/one-context.d/loc-10-network.d/netcfg-vyos
etc/one-context.d/loc-16-gen-env
usr/lib/systemd/system/one-context-reconfigure-delayed.service
usr/lib/systemd/system/one-context-reconfigure.service
usr/lib/systemd/system/one-context-reconfigure.timer
usr/lib/systemd/system/one-context.service
usr/lib/udev/rules.d/65-context-vyos.rules
usr/sbin/one-context-run
usr/sbin/one-contextd
usr/share/doc/one-context-vyos/README.md
EOF
sort -o "${TEST_DIR}/expected" "${TEST_DIR}/expected"

diff -u "${TEST_DIR}/expected" "${TEST_DIR}/actual"

ar -p "${PACKAGE}" control.tar.gz >"${TEST_DIR}/control.tar.gz"
tar -xzOf "${TEST_DIR}/control.tar.gz" ./control >"${TEST_DIR}/control"
grep -Fq 'Depends: util-linux, bash, curl, login' "${TEST_DIR}/control"
if grep -Eq 'ruby|NetworkManager|netplan|cloud-init|openssh' "${TEST_DIR}/control"; then
    echo 'non-VyOS dependency found in package metadata' >&2
    exit 1
fi

echo 'Minimal VyOS package test passed'
