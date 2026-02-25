#!python
"""
Setup/teardown for mood gauge hooks and statusline.

Usage:
    ./mood_setup.py install     Add hooks + statusline to settings.json
    ./mood_setup.py uninstall   Remove mood hooks + statusline
    ./mood_setup.py status      Show current installation state
"""
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SETTINGS_PATH = Path(os.path.expanduser("~")) / ".claude" / "settings.json"

# Forward slashes for Git Bash compatibility
HOOK_SCRIPT = str(SCRIPT_DIR / "mood_hook.py").replace("\\", "/")
STATUSLINE_SCRIPT = str(SCRIPT_DIR / "mood_statusline.py").replace("\\", "/")

# Marker string for detecting our hooks during uninstall
MOOD_MARKER = "mood_hook.py"
MOOD_SL_MARKER = "mood_statusline.py"

# Python command — on this Windows system, 'python' is in PATH
PYTHON = "python"

# Hook events we register (all async to never block Claude Code)
HOOK_EVENTS = ["PostToolUse", "PostToolUseFailure", "PreCompact", "UserPromptSubmit"]


def _moodHookEntry() -> dict:
    """Build a single hook matcher entry for mood."""
    return {
        "hooks": [
            {
                "type": "command",
                "command": f"{PYTHON} {HOOK_SCRIPT}",
            }
        ]
    }


def _loadSettings() -> dict:
    if SETTINGS_PATH.exists():
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _saveSettings(settings: dict):
    # Backup first
    if SETTINGS_PATH.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backupPath = SETTINGS_PATH.parent / f"settings.bak-{ts}.json"
        shutil.copy2(str(SETTINGS_PATH), str(backupPath))
        print(f"  Backup: {backupPath}")

    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def _isMoodHook(entry: dict) -> bool:
    """Check if a hook entry belongs to mood gauge."""
    return any(
        MOOD_MARKER in h.get("command", "")
        for h in entry.get("hooks", [])
    )


def SETUP_Install():
    """Add mood hooks and statusline. Preserves all existing hooks."""
    settings = _loadSettings()
    hooks = settings.setdefault("hooks", {})

    for event in HOOK_EVENTS:
        existingList = hooks.get(event, [])
        # Remove old mood entries (idempotent re-install)
        existingList = [e for e in existingList if not _isMoodHook(e)]
        existingList.append(_moodHookEntry())
        hooks[event] = existingList

    settings["hooks"] = hooks

    # Statusline (only one can exist)
    settings["statusLine"] = {
        "type": "command",
        "command": f"{PYTHON} {STATUSLINE_SCRIPT}",
    }

    _saveSettings(settings)
    print("[OK] Mood gauge installed.")
    print(f"  Hooks: {', '.join(HOOK_EVENTS)}")
    print(f"  Statusline: {STATUSLINE_SCRIPT}")
    print(f"  Settings: {SETTINGS_PATH}")
    print("  Restart Claude Code for changes to take effect.")


def SETUP_Uninstall():
    """Remove mood hooks and statusline. Preserve everything else."""
    settings = _loadSettings()
    hooks = settings.get("hooks", {})

    removedEvents = []
    for event in list(hooks.keys()):
        before = len(hooks[event])
        hooks[event] = [e for e in hooks[event] if not _isMoodHook(e)]
        if len(hooks[event]) < before:
            removedEvents.append(event)
        if not hooks[event]:
            del hooks[event]

    settings["hooks"] = hooks

    # Remove statusline only if it's ours
    sl = settings.get("statusLine", {})
    slRemoved = False
    if isinstance(sl, dict) and MOOD_SL_MARKER in sl.get("command", ""):
        del settings["statusLine"]
        slRemoved = True

    _saveSettings(settings)
    print("[OK] Mood gauge uninstalled.")
    if removedEvents:
        print(f"  Hooks removed from: {', '.join(removedEvents)}")
    if slRemoved:
        print("  Statusline removed.")
    print("  Other hooks preserved.")


def SETUP_Status():
    """Show current installation state."""
    settings = _loadSettings()
    hooks = settings.get("hooks", {})

    moodEvents = []
    for event, entries in hooks.items():
        if any(_isMoodHook(e) for e in entries):
            moodEvents.append(event)

    sl = settings.get("statusLine", {})
    slInstalled = isinstance(sl, dict) and MOOD_SL_MARKER in sl.get("command", "")

    print("Mood gauge status:")
    print(f"  Hooks: {', '.join(moodEvents) if moodEvents else 'none'}")
    print(f"  Statusline: {'installed' if slInstalled else 'not installed'}")

    from mood_config import MCFG_Load
    cfg = MCFG_Load()
    print(f"  Mode: {cfg.get('mode', 'unknown')}")

    dataDir = SCRIPT_DIR / "data" / "sessions"
    if dataDir.exists():
        sessionFiles = list(dataDir.glob("*.json"))
        print(f"  Session files: {len(sessionFiles)}")
    else:
        print("  Session files: 0")


def main():
    usage = "Usage: mood_setup.py [install|uninstall|status]"
    if len(sys.argv) < 2 or sys.argv[1] not in ("install", "uninstall", "status"):
        print(usage)
        sys.exit(1)

    cmd = sys.argv[1]
    {"install": SETUP_Install, "uninstall": SETUP_Uninstall, "status": SETUP_Status}[cmd]()


if __name__ == "__main__":
    main()
