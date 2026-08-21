"""Block killing Office processes by IMAGE NAME. Kill by PID instead.

Why this exists: `taskkill /F /IM EXCEL.EXE` kills EVERY Excel on the machine,
including the user's own workbook with unsaved changes. Worse, force-killing
Excel mid-clipboard-operation leaves the Windows clipboard wedged machine-wide
— OpenClipboard then fails with ACCESS_DENIED and no owning window, which
needs a sign-out to clear. That happened during this project, twice, after
saying it would not happen again.

`build.shutdown()` already kills only the pid it started. This hook makes the
image-wide form unavailable rather than relying on remembering.

    allowed   taskkill /F /PID 1234        Stop-Process -Id 1234
    blocked   taskkill /F /IM EXCEL.EXE    Stop-Process -Name EXCEL
              Get-Process EXCEL | Stop-Process

Reads the PreToolUse payload on stdin; prints a deny decision or nothing.

It matches the command TEXT, so it also fires on a quoted mention - a commit
message containing the literal command is refused. That is deliberate: a false
positive costs a reword, a false negative costs the user's unsaved work. Write
`/IM <image>` when describing it.
"""

import json
import re
import sys

APPS = r"EXCEL|POWERPNT|WINWORD|MSACCESS|OUTLOOK"

# Each pattern is one way to name an image rather than a pid.
PATTERNS = [
    # taskkill /IM EXCEL.EXE   (also //IM, as Git Bash requires)
    rf"taskkill[^&|;]*/{{1,2}}IM[\s=:]+[\"']?({APPS})",
    # Stop-Process -Name EXCEL / -ProcessName EXCEL
    rf"Stop-Process[^&|;]*-(?:Process)?Name\s+[\"']?({APPS})",
    # Get-Process EXCEL ... | Stop-Process
    rf"Get-Process\s+[^|]*({APPS})[^|]*\|[^|]*Stop-Process",
    # pkill / killall on an Office image
    rf"(?:pkill|killall)[^&|;]*({APPS})",
]

REASON = (
    "Kill by PID only. An image-wide kill (/IM, -Name, Get-Process | "
    "Stop-Process) destroys the user's own Excel and any unsaved work, and "
    "force-killing Excel mid-copy wedges the Windows clipboard machine-wide "
    "until they sign out. Use build.shutdown(), which kills only the pid it "
    "started, or taskkill /F /PID <pid>."
)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:          # noqa: BLE001 - a hook must never break the tool
        return
    command = str(payload.get("tool_input", {}).get("command", ""))
    if not command:
        return
    if not any(re.search(p, command, re.IGNORECASE) for p in PATTERNS):
        return
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }, sys.stdout)


if __name__ == "__main__":
    main()
