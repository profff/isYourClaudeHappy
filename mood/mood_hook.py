#!python
"""
Claude Code hook handler for mood gauge.
Handles: PostToolUse, PostToolUseFailure, PreCompact, UserPromptSubmit.
Writes signals to per-session state file in data/sessions/.
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stdin.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from mood_config import MCFG_Load
from mood_engine import MOOD_Update

DATA_DIR = SCRIPT_DIR / "data" / "sessions"


# --- State management ---

def _newState(sessionId: str) -> dict:
    """Create fresh state for a new session."""
    now = time.time()
    return {
        "session_id": sessionId,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "signals": {
            "tool_success_count": 0,
            "tool_failure_count": 0,
            "tool_calls_timestamps": [],
            "last_failure_streak": 0,
            "compaction_count": 0,
            "last_compaction_at": None,
            "lines_added_snapshot": 0,
            "lines_removed_snapshot": 0,
            "prompt_count": 0,
            "session_start_time": now,
        },
        "mood": {
            "valence": 0.0,
            "arousal": 0.3,
            "label": "Calme",
            "face": "(-.-)",
            "last_computed_at": now,
        },
    }


def STATE_Load(sessionId: str) -> dict:
    """Load or create state for a session."""
    statePath = DATA_DIR / f"{sessionId}.json"
    if statePath.exists():
        try:
            with open(statePath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return _newState(sessionId)


def STATE_Save(sessionId: str, stateData: dict):
    """Atomically save state (write tmp + rename)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    statePath = DATA_DIR / f"{sessionId}.json"
    fd, tmpPath = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(stateData, f, indent=2)
        os.replace(tmpPath, str(statePath))
    except Exception:
        try:
            os.unlink(tmpPath)
        except OSError:
            pass
        raise


# --- Timestamp housekeeping ---

def _pruneTimestamps(signals: dict):
    """Keep only last 5 minutes of tool call timestamps."""
    cutoff = time.time() - 300
    signals["tool_calls_timestamps"] = [
        t for t in signals["tool_calls_timestamps"] if t > cutoff
    ]


# --- Event handlers ---

def HOOK_HandlePostToolUse(hookInput: dict, state: dict) -> dict:
    signals = state["signals"]
    signals["tool_success_count"] += 1
    signals["last_failure_streak"] = 0
    signals["tool_calls_timestamps"].append(time.time())
    _pruneTimestamps(signals)
    return state


def HOOK_HandlePostToolUseFailure(hookInput: dict, state: dict) -> dict:
    signals = state["signals"]
    signals["tool_failure_count"] += 1
    signals["last_failure_streak"] += 1
    signals["tool_calls_timestamps"].append(time.time())
    _pruneTimestamps(signals)
    return state


def HOOK_HandlePreCompact(hookInput: dict, state: dict) -> dict:
    signals = state["signals"]
    signals["compaction_count"] += 1
    signals["last_compaction_at"] = time.time()
    return state


def HOOK_HandleUserPromptSubmit(hookInput: dict, state: dict) -> dict:
    signals = state["signals"]
    signals["prompt_count"] += 1
    return state


HANDLERS = {
    "PostToolUse": HOOK_HandlePostToolUse,
    "PostToolUseFailure": HOOK_HandlePostToolUseFailure,
    "PreCompact": HOOK_HandlePreCompact,
    "UserPromptSubmit": HOOK_HandleUserPromptSubmit,
}


# --- stdin reading (timeout for PowerShell compat) ---

def _readStdinWithTimeout(timeoutSec=3) -> str | None:
    result = {"data": None}

    def _read():
        try:
            result["data"] = sys.stdin.read()
        except Exception:
            pass

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()
    thread.join(timeout=timeoutSec)
    return result["data"] if not thread.is_alive() else None


# --- Main ---

def main():
    rawInput = _readStdinWithTimeout()
    if not rawInput:
        return

    try:
        hookInput = json.loads(rawInput.strip())
    except (json.JSONDecodeError, ValueError):
        return

    config = MCFG_Load()
    if config.get("mode") != "full":
        return

    sessionId = hookInput.get("session_id", "")
    event = hookInput.get("hook_event_name", "")
    if not sessionId or event not in HANDLERS:
        return

    try:
        state = STATE_Load(sessionId)
        state = HANDLERS[event](hookInput, state)
        # Recompute mood (context% not available from hooks, use 0)
        state = MOOD_Update(state, contextPct=0, config=config)
        STATE_Save(sessionId, state)
    except Exception:
        pass  # Never block Claude Code


if __name__ == "__main__":
    main()
