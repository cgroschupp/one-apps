#!/usr/bin/env bash
set -euo pipefail

PACKAGE=${PACKAGE:-one-vyos-vrouter}
VERSION=${VERSION:-0.2.0}
RELEASE=${RELEASE:-1}
ARCH=${ARCH:-all}
MAINTAINER=${MAINTAINER:-OpenNebula Systems <contact@opennebula.io>}

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH='' cd -- "${SCRIPT_DIR}/.." && pwd)
BUILD_DIR=$(mktemp -d)
PACKAGE_ROOT="${BUILD_DIR}/package"
CONTROL_ROOT="${BUILD_DIR}/control"
OUT_DIR="${PROJECT_DIR}/out"
DEB="${OUT_DIR}/${PACKAGE}_${VERSION}-${RELEASE}_${ARCH}.deb"

cleanup() {
    rm -rf "${BUILD_DIR}"
}
trap cleanup EXIT

mkdir -p "${PACKAGE_ROOT}/usr/lib/one-vyos-vrouter"
mkdir -p "${PACKAGE_ROOT}/usr/sbin"
mkdir -p "${PACKAGE_ROOT}/lib/systemd/system"
mkdir -p "${PACKAGE_ROOT}/usr/share/doc/${PACKAGE}"
mkdir -p "${CONTROL_ROOT}" "${OUT_DIR}"

cp -R "${PROJECT_DIR}/one_vrouter" "${PACKAGE_ROOT}/usr/lib/one-vyos-vrouter/"
cp "${SCRIPT_DIR}/one-vyos-vrouter" "${PACKAGE_ROOT}/usr/sbin/one-vyos-vrouter"
cp "${SCRIPT_DIR}/one-vyos-vrouter.service" "${PACKAGE_ROOT}/lib/systemd/system/"
cp "${PROJECT_DIR}/README.md" "${PACKAGE_ROOT}/usr/share/doc/${PACKAGE}/README.md"
find "${PACKAGE_ROOT}" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${PACKAGE_ROOT}" -type f -name '*.py[co]' -delete
chmod 0755 "${PACKAGE_ROOT}/usr/sbin/one-vyos-vrouter"
chmod 0644 "${PACKAGE_ROOT}/lib/systemd/system/one-vyos-vrouter.service"

cat > "${CONTROL_ROOT}/control" <<EOF
Package: ${PACKAGE}
Version: ${VERSION}-${RELEASE}
Section: admin
Priority: optional
Architecture: ${ARCH}
Maintainer: ${MAINTAINER}
Depends: python3 (>= 3.9), one-context
Description: OpenNebula Virtual Router controller for VyOS
 Polls OneGate and reconciles OpenNebula VRouter interfaces, routing, NAT,
 DHCP, DNS, VRRP, WireGuard, IPVS, and HAProxy into native VyOS config.
EOF

cat > "${CONTROL_ROOT}/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
    systemctl enable one-vyos-vrouter.service || true
fi
exit 0
EOF

cat > "${CONTROL_ROOT}/prerm" <<'EOF'
#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1; then
    systemctl disable --now one-vyos-vrouter.service || true
fi
exit 0
EOF
chmod 0755 "${CONTROL_ROOT}/postinst" "${CONTROL_ROOT}/prerm"

(
    cd "${PACKAGE_ROOT}"
    if command -v md5sum >/dev/null 2>&1; then
        find . -type f -exec md5sum {} \; | sed 's#  ./#  #' > "${CONTROL_ROOT}/md5sums"
    elif command -v md5 >/dev/null 2>&1; then
        find . -type f -exec md5 -r {} \; | sed 's#  ./#  #' > "${CONTROL_ROOT}/md5sums"
    fi
)

printf '2.0\n' > "${BUILD_DIR}/debian-binary"
(
    cd "${CONTROL_ROOT}"
    tar --uid 0 --gid 0 --uname root --gname root -czf "${BUILD_DIR}/control.tar.gz" .
)
(
    cd "${PACKAGE_ROOT}"
    tar --uid 0 --gid 0 --uname root --gname root -czf "${BUILD_DIR}/data.tar.gz" .
)
rm -f "${DEB}"
(
    cd "${BUILD_DIR}"
    ar -qcS "${DEB}" debian-binary control.tar.gz data.tar.gz
)
echo "${DEB}"
