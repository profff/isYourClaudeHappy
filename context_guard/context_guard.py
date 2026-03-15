#!python
"""
Context Guard — Hook UserPromptSubmit pour limiter le contexte de Claude Code.

Lit le % d'utilisation du contexte depose par la statusline mood
(~/.claude/context_guard/<session_id>.json) et compare aux seuils.

Si le contexte depasse le seuil, bloque le prompt ou avertit Claude.

Config via ~/.claude/context_guard.json:
  {
    "warn_pct": 15,
    "block_pct": 20,
    "enabled": true
  }

Seuils en % du contexte modele (ex: 20% de 1M = 200K).

Env var overrides:
  CONTEXT_GUARD_WARN_PCT=15
  CONTEXT_GUARD_BLOCK_PCT=20
  CONTEXT_GUARD_ENABLED=true|false
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stdin.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_CONFIG = {
    "warn_pct": 15,
    "block_pct": 20,
    "enabled": True,
}

CONFIG_PATH = Path.home() / ".claude" / "context_guard.json"
CONTEXT_SHARE_DIR = Path.home() / ".claude" / "context_guard"


def CTXG_LoadConfig():
    """Load config from file, env var override, or defaults."""
    config = dict(DEFAULT_CONFIG)

    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                user = json.load(f)
            config.update(user)
        except (json.JSONDecodeError, OSError):
            pass

    if os.environ.get("CONTEXT_GUARD_WARN_PCT"):
        config["warn_pct"] = int(os.environ["CONTEXT_GUARD_WARN_PCT"])
    if os.environ.get("CONTEXT_GUARD_BLOCK_PCT"):
        config["block_pct"] = int(os.environ["CONTEXT_GUARD_BLOCK_PCT"])
    if os.environ.get("CONTEXT_GUARD_ENABLED"):
        config["enabled"] = os.environ["CONTEXT_GUARD_ENABLED"].lower() in (
            "1", "true", "yes",
        )

    return config


def CTXG_ReadSessionInfo(sessionId):
    """Read session file written by statusline.

    Returns dict with used_percentage and optional overrides, or None.
    """
    sharePath = CONTEXT_SHARE_DIR / f"{sessionId}.json"
    if not sharePath.exists():
        return None
    try:
        with open(sharePath, encoding="utf-8") as f:
            info = json.load(f)
        # Stale check — ignore if older than 5 minutes
        if time.time() - info.get("updated_at", 0) > 300:
            return None
        return info
    except (json.JSONDecodeError, OSError):
        return None


def CTXG_SetSessionOverride(sessionId, warnPct=None, blockPct=None):
    """Set per-session threshold overrides (preserved across statusline writes)."""
    sharePath = CONTEXT_SHARE_DIR / f"{sessionId}.json"
    try:
        if sharePath.exists():
            with open(sharePath, encoding="utf-8") as f:
                info = json.load(f)
        else:
            info = {"session_id": sessionId}
        if warnPct is not None:
            info["override_warn_pct"] = warnPct
        if blockPct is not None:
            info["override_block_pct"] = blockPct
        with open(sharePath, "w", encoding="utf-8") as f:
            json.dump(info, f)
        return True
    except OSError:
        return False


def CTXG_Evaluate(usedPct, config, sessionInfo=None):
    """Evaluate context usage against thresholds.

    Session overrides take priority over global config.
    Returns "ok", "warn", or "block".
    """
    warnPct = config["warn_pct"]
    blockPct = config["block_pct"]
    if sessionInfo:
        warnPct = sessionInfo.get("override_warn_pct", warnPct)
        blockPct = sessionInfo.get("override_block_pct", blockPct)

    if usedPct >= blockPct:
        return "block"
    elif usedPct >= warnPct:
        return "warn"
    return "ok"


def CTXG_CleanupOldFiles(maxAgeHours=48):
    """Remove stale context info files."""
    if not CONTEXT_SHARE_DIR.exists():
        return
    cutoff = time.time() - maxAgeHours * 3600
    for f in CONTEXT_SHARE_DIR.glob("*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


# --- Hook ---

def _readStdin(timeoutSec=3):
    result = {"data": None}

    def reader():
        try:
            result["data"] = sys.stdin.read()
        except Exception:
            pass

    thread = threading.Thread(target=reader)
    thread.daemon = True
    thread.start()
    thread.join(timeout=timeoutSec)
    return result["data"]


def hookMain():
    raw = _readStdin()
    if not raw:
        return

    try:
        hookInput = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        return

    if hookInput.get("hook_event_name") != "UserPromptSubmit":
        return

    config = CTXG_LoadConfig()
    if not config["enabled"]:
        return

    sessionId = hookInput.get("session_id", "")
    if not sessionId:
        return

    sessionInfo = CTXG_ReadSessionInfo(sessionId)
    if sessionInfo is None:
        return

    usedPct = sessionInfo.get("used_percentage", 0)
    if usedPct <= 0:
        return

    level = CTXG_Evaluate(usedPct, config, sessionInfo)

    # Effective thresholds (session override or global)
    warnPct = sessionInfo.get("override_warn_pct", config["warn_pct"])
    blockPct = sessionInfo.get("override_block_pct", config["block_pct"])

    if level == "block":
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"Context Guard: context at {usedPct}% "
                f"(limit: {blockPct}%). "
                f"Run /compact to continue."
            ),
        }))

    elif level == "warn":
        print(json.dumps({
            "additionalContext": (
                f"[CONTEXT GUARD] Context at {usedPct}% "
                f"(warn: {warnPct}%, block: {blockPct}%). "
                f"Consider running /compact soon. "
                f"Briefly mention this to the user."
            ),
            "systemMessage": (
                f"Context Guard: {usedPct}% "
                f"(warn: {warnPct}%, block: {blockPct}%)"
            ),
        }))

    CTXG_CleanupOldFiles()


# --- CLI (skill) ---

def cliMain():
    args = sys.argv[1:] or ["status"]
    cmd = args[0].lower()

    if cmd == "status":
        config = CTXG_LoadConfig()
        print(f"Context Guard")
        print(f"  Enabled:  {config['enabled']}")
        print(f"  Warn at:  {config['warn_pct']}%")
        print(f"  Block at: {config['block_pct']}%")
        if CONTEXT_SHARE_DIR.exists():
            files = sorted(CONTEXT_SHARE_DIR.glob("*.json"),
                           key=lambda f: f.stat().st_mtime, reverse=True)
            for f in files[:3]:
                try:
                    info = json.loads(f.read_text(encoding="utf-8"))
                    sid = info.get("session_id", "?")[:8]
                    pct = info.get("used_percentage", 0)
                    age = time.time() - info.get("updated_at", 0)
                    overrides = ""
                    if "override_warn_pct" in info or "override_block_pct" in info:
                        ow = info.get("override_warn_pct", "-")
                        ob = info.get("override_block_pct", "-")
                        overrides = f" [override: warn={ow}%, block={ob}%]"
                    print(f"  Session {sid}...: {pct}% — {age:.0f}s ago{overrides}")
                except Exception:
                    pass

    elif cmd in ("enable", "on"):
        config = CTXG_LoadConfig()
        config["enabled"] = True
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print("Context Guard enabled.")

    elif cmd in ("disable", "off"):
        config = CTXG_LoadConfig()
        config["enabled"] = False
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print("Context Guard disabled.")

    elif cmd == "set" and len(args) >= 3:
        config = CTXG_LoadConfig()
        param, value = args[1].lower(), int(args[2])
        if param == "warn":
            config["warn_pct"] = value
            print(f"Warn threshold: {value}%")
        elif param == "block":
            config["block_pct"] = value
            print(f"Block threshold: {value}%")
        else:
            print(f"Unknown param: {param}. Use 'warn' or 'block'.")
            return
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    elif cmd == "session" and len(args) >= 3:
        # /ctxguard session <session_id> [warn <pct>] [block <pct>] [reset]
        sid = args[1]
        if args[2].lower() == "reset":
            sharePath = CONTEXT_SHARE_DIR / f"{sid}.json"
            if sharePath.exists():
                with open(sharePath, encoding="utf-8") as f:
                    info = json.load(f)
                info.pop("override_warn_pct", None)
                info.pop("override_block_pct", None)
                with open(sharePath, "w", encoding="utf-8") as f:
                    json.dump(info, f)
                print(f"Session overrides cleared for {sid[:8]}...")
            else:
                print(f"No session file for {sid[:8]}...")
        elif len(args) >= 4:
            param, value = args[2].lower(), int(args[3])
            warnPct = value if param == "warn" else None
            blockPct = value if param == "block" else None
            if CTXG_SetSessionOverride(sid, warnPct=warnPct, blockPct=blockPct):
                print(f"Session {sid[:8]}...: {param} override set to {value}%")
            else:
                print("Failed to set override.")

    else:
        print("Usage:")
        print("  /ctxguard status                       — show config + sessions")
        print("  /ctxguard set warn|block <pct>         — set global threshold")
        print("  /ctxguard session <id> warn|block <pct> — set per-session override")
        print("  /ctxguard session <id> reset            — clear session overrides")
        print("  /ctxguard enable|disable                — toggle on/off")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cliMain()
    else:
        hookMain()
