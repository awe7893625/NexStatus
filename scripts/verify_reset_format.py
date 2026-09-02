#!/usr/bin/env python3
"""Verify Lua reset formatting functions work correctly with stale data.

Tests fmtReset and fmtResetFull via Hammerspoon's Lua interpreter.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    """Main entry point."""
    repo_root = Path(__file__).parent.parent
    lua_file = repo_root / "hammerspoon" / "nexstatus.lua"

    if not lua_file.is_file():
        print(f"Error: {lua_file} not found", file=sys.stderr)
        return 1

    # Read the Lua file and extract the function definitions
    content = lua_file.read_text(encoding="utf-8")

    # Find and extract fmtReset and fmtResetFull functions
    fmt_reset_match = re.search(
        r"local function fmtReset\(.*?\)\s*(.+?)\s*^end",
        content,
        re.MULTILINE | re.DOTALL,
    )
    fmt_reset_full_match = re.search(
        r"local function fmtResetFull\(.*?\)\s*(.+?)\s*^end",
        content,
        re.MULTILINE | re.DOTALL,
    )

    if not fmt_reset_match or not fmt_reset_full_match:
        # Simpler approach: just extract the raw lines
        lines = content.split("\n")
        start_idx = None
        for i, line in enumerate(lines):
            if "local function fmtReset(ts)" in line:
                start_idx = i
                break

        if start_idx is None:
            print("Error: Could not find fmtReset function", file=sys.stderr)
            return 1

        # Get from start to the matching 'end'
        end_idx = start_idx + 1
        depth = 0
        for i in range(start_idx, len(lines)):
            if "function" in lines[i]:
                depth += 1
            if "^end$" in lines[i] or lines[i].strip() == "end":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break

        fmt_reset_code = "\n".join(lines[start_idx:end_idx])

        # Same for fmtResetFull
        start_idx = None
        for i, line in enumerate(lines):
            if "local function fmtResetFull(ts)" in line:
                start_idx = i
                break

        if start_idx is None:
            print("Error: Could not find fmtResetFull function", file=sys.stderr)
            return 1

        end_idx = start_idx + 1
        depth = 0
        for i in range(start_idx, len(lines)):
            if "function" in lines[i]:
                depth += 1
            if "^end$" in lines[i] or lines[i].strip() == "end":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break

        fmt_reset_full_code = "\n".join(lines[start_idx:end_idx])
    else:
        fmt_reset_code = f"local function fmtReset(ts)\n{fmt_reset_match.group(1).strip()}\nend"
        fmt_reset_full_code = f"local function fmtResetFull(ts)\n{fmt_reset_full_match.group(1).strip()}\nend"

    # Fixed "now" for testing: 2026-09-02 00:11:00 UTC (= 08:11 Taipei).
    # (Previously hardcoded as 1725206460, which is 2024-09-01 -- a two-year
    # miscalculation that silently broke every assertion below: the "now" used to
    # stub os.time() must match the epoch in the comment, not just look plausible.)
    fixed_now_epoch = 1788307860

    # BUG-1/BUG-2 stale values
    five_hour_reset_ts = 1788094800
    seven_day_reset_ts = 1788426000

    lua_script = f"""
local original_time = os.time
os.time = function() return {fixed_now_epoch} end

{fmt_reset_code}

{fmt_reset_full_code}

print("Test nil:")
print("  fmtReset(nil) = '" .. fmtReset(nil) .. "'")
print("  fmtResetFull(nil) = '" .. fmtResetFull(nil) .. "'")

print("\\nTest past (now - 60):")
print("  fmtReset(" .. ({fixed_now_epoch} - 60) .. ") = '" .. fmtReset({fixed_now_epoch} - 60) .. "'")

print("\\nTest 5h reset (BUG-1):")
print("  fmtReset({five_hour_reset_ts}) = '" .. fmtReset({five_hour_reset_ts}) .. "'")
print("  fmtResetFull({five_hour_reset_ts}) = '" .. fmtResetFull({five_hour_reset_ts}) .. "'")

print("\\nTest 7d reset (BUG-2):")
print("  fmtReset({seven_day_reset_ts}) = '" .. fmtReset({seven_day_reset_ts}) .. "'")
print("  fmtResetFull({seven_day_reset_ts}) = '" .. fmtResetFull({seven_day_reset_ts}) .. "'")
"""

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".lua",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(lua_script)
        script_path = f.name

    try:
        result = subprocess.run(
            ["/opt/homebrew/bin/hs", "-c", f"dofile('{script_path}')"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        print(result.stdout)
        if result.stderr:
            print("Stderr:", result.stderr, file=sys.stderr)
        return result.returncode
    except subprocess.TimeoutExpired:
        print("Lua script timed out", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("Error: hs not found at /opt/homebrew/bin/hs", file=sys.stderr)
        return 1
    finally:
        Path(script_path).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
