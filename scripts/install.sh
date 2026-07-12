#!/usr/bin/env bash
# Install NexStatus into Hammerspoon.
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HS_DIR="${HOME}/.hammerspoon"
INIT="${HS_DIR}/init.lua"
LINK="${HS_DIR}/nexstatus.lua"
MARKER_BEGIN="-- nexstatus:begin"
MARKER_END="-- nexstatus:end"

echo "NexStatus root: ${ROOT}"

if [[ ! -d "${HS_DIR}" ]]; then
  echo "Hammerspoon config dir not found: ${HS_DIR}"
  echo "Install Hammerspoon first: https://www.hammerspoon.org/"
  exit 1
fi

if [[ -L "${INIT}" ]]; then
  echo "Refusing to modify symlinked Hammerspoon init: ${INIT}"
  exit 1
fi

# Symlink the MenuBar module
ln -sfn "${ROOT}/hammerspoon/nexstatus.lua" "${LINK}"
echo "Linked ${LINK} → hammerspoon/nexstatus.lua"

# Ensure collector is executable
chmod +x "${ROOT}/nexstatus/collector.py"
chmod +x "${ROOT}/scripts/build-native-menubar.sh"

# Inject load block into init.lua (idempotent)
BLOCK=$(cat <<'EOF'
${MARKER_BEGIN}
-- NexStatus — Claude / Codex / OpenCode Go / Grok / Memory MenuBar
pcall(function()
  local home = os.getenv("HOME") or ""
  local ns = dofile(home .. "/.hammerspoon/nexstatus.lua")
  ns.start()
  _G.NexStatus = ns
end)
${MARKER_END}
EOF
)
# Expand only the fixed marker tokens. Repository paths are never interpolated
# into Lua source, so quotes/newlines in a checkout path cannot inject code.
BLOCK="${BLOCK//'${MARKER_BEGIN}'/${MARKER_BEGIN}}"
BLOCK="${BLOCK//'${MARKER_END}'/${MARKER_END}}"

if [[ -f "${INIT}" ]] && grep -qF -- "${MARKER_BEGIN}" "${INIT}"; then
  # Replace existing block
  tmp="$(mktemp "${INIT}.tmp.XXXXXX")"
  mode="$(stat -f '%Lp' "${INIT}")"
  awk -v begin="${MARKER_BEGIN}" -v end="${MARKER_END}" '
    index($0, begin) { skip=1; next }
    index($0, end) { skip=0; next }
    !skip { print }
  ' "${INIT}" > "${tmp}"
  printf "%s\n" "${BLOCK}" >> "${tmp}"
  chmod "${mode}" "${tmp}"
  mv "${tmp}" "${INIT}"
  echo "Updated NexStatus block in ${INIT}"
else
  printf "\n%s\n" "${BLOCK}" >> "${INIT}"
  echo "Appended NexStatus block to ${INIT}"
fi

# First snapshot
/usr/bin/python3 "${ROOT}/nexstatus/collector.py" --print || true

# Build and install the native status item. The Hammerspoon module remains the
# detailed glass panel, while Swift owns the notch-safe Menu Bar presentation.
"${ROOT}/scripts/build-native-menubar.sh"

# Reload Hammerspoon if CLI available
if command -v hs >/dev/null 2>&1; then
  hs -c 'hs.reload()' 2>/dev/null || true
  echo "Hammerspoon reloaded"
else
  echo "Open Hammerspoon and click Reload Config (or install hs CLI)."
fi

echo ""
echo "Done. Look for the rotating native MenuBar title: C… / G… / H…"
echo "Click it to open the glass panel."
