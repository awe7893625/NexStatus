#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="${ROOT}/.build/native-menubar"
APP="${BUILD}/NexStatusMenuBar.app"
INSTALL_APP="${HOME}/Applications/NexStatusMenuBar.app"
AGENT="${HOME}/Library/LaunchAgents/com.nexstatus.menubar.plist"

mkdir -p "${APP}/Contents/MacOS" "${HOME}/Applications" "${HOME}/Library/LaunchAgents" "${HOME}/.cache/nexstatus"

/usr/bin/swiftc -O -framework AppKit -framework Foundation \
  "${ROOT}/native/NexStatusMenuBar.swift" \
  -o "${APP}/Contents/MacOS/NexStatusMenuBar"

cp "${ROOT}/native/Info.plist" "${APP}/Contents/Info.plist"
rm -rf "${INSTALL_APP}"
cp -R "${APP}" "${INSTALL_APP}"
touch "${HOME}/.cache/nexstatus/native-menubar.enabled"

sed "s|__APP_PATH__|${INSTALL_APP}/Contents/MacOS/NexStatusMenuBar|g" \
  "${ROOT}/native/com.nexstatus.menubar.plist.template" > "${AGENT}"
chmod 600 "${AGENT}"

launchctl bootout "gui/${UID}/com.nexstatus.menubar" 2>/dev/null || true
launchctl bootstrap "gui/${UID}" "${AGENT}"
launchctl enable "gui/${UID}/com.nexstatus.menubar"
launchctl kickstart -k "gui/${UID}/com.nexstatus.menubar"

echo "Installed ${INSTALL_APP}"
