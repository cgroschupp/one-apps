#!/usr/bin/env bash
set -euo pipefail

PACKAGE=${PACKAGE:-one-context-vyos}
VERSION=${VERSION:-7.4.0}
RELEASE=${RELEASE:-0}
ARCH=${ARCH:-all}
MAINTAINER=${MAINTAINER:-OpenNebula Systems <contact@opennebula.io>}

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
BUILD_DIR=$(mktemp -d)
PACKAGE_ROOT="${BUILD_DIR}/package"
CONTROL_ROOT="${BUILD_DIR}/control"
OUT_DIR="${SCRIPT_DIR}/out"
DEB="${OUT_DIR}/${PACKAGE}_${VERSION}-${RELEASE}.deb"

cleanup()
{
    rm -rf "${BUILD_DIR}"
}
trap cleanup EXIT

mkdir -p "${PACKAGE_ROOT}" "${CONTROL_ROOT}" "${OUT_DIR}"

(
    cd "${SCRIPT_DIR}"
    TARGET=vyos TYPE=dir VERSION="${VERSION}" RELEASE="${RELEASE}" \
        OUT="${PACKAGE_ROOT}" ./generate.sh >/dev/null
)

cat >"${CONTROL_ROOT}/control" <<EOF
Package: ${PACKAGE}
Version: ${VERSION}-${RELEASE}
Section: admin
Priority: optional
Architecture: ${ARCH}
Maintainer: ${MAINTAINER}
Depends: util-linux, bash, curl, login
Provides: one-context
Replaces: one-context, addon-context
Conflicts: one-context, one-context-ec2, addon-context
Description: OpenNebula contextualization package for VyOS
 Reads the OpenNebula CONTEXT disk, exports the VRouter environment, and
 applies addresses, routes, DNS, and hostname through the native VyOS
 configuration interface.
EOF

cp "${SCRIPT_DIR}/pkg/postinstall.vyos" "${CONTROL_ROOT}/postinst"
cp "${SCRIPT_DIR}/pkg/preuninstall.vyos" "${CONTROL_ROOT}/prerm"
cp "${SCRIPT_DIR}/pkg/postuninstall" "${CONTROL_ROOT}/postrm"
chmod 0755 "${CONTROL_ROOT}/postinst" "${CONTROL_ROOT}/prerm" "${CONTROL_ROOT}/postrm"

(
    cd "${PACKAGE_ROOT}"
    if command -v md5sum >/dev/null 2>&1; then
        find . -type f -exec md5sum {} \; | sed 's#  ./#  #' >"${CONTROL_ROOT}/md5sums"
    elif command -v md5 >/dev/null 2>&1; then
        find . -type f -exec md5 -r {} \; | sed 's#  ./#  #' >"${CONTROL_ROOT}/md5sums"
    fi
)

printf '2.0\n' >"${BUILD_DIR}/debian-binary"
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
