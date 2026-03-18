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


def _getMaxTokensFromSessions():
    """Find max_tokens from the most recent session file that has it."""
    if not CONTEXT_SHARE_DIR.exists():
        return 0
    files = sorted(CONTEXT_SHARE_DIR.glob("*.json"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files:
        try:
            info = json.loads(f.read_text(encoding="utf-8"))
            maxTok = info.get("max_tokens", 0)
            if maxTok and maxTok > 0:
                return maxTok
        except (json.JSONDecodeError, OSError):
            pass
    return 0


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

    event = hookInput.get("hook_event_name", "")
    if event not in ("UserPromptSubmit", "PostToolUse"):
        return

    config = CTXG_LoadConfig()
    if not config["enabled"]:
        return

    # Bypass: let /ctxguard through (needs to run even when blocked)
    prompt = hookInput.get("prompt", "")
    if event == "UserPromptSubmit" and prompt.strip().startswith("/ctxguard"):
        return

    sessionId = hookInput.get("session_id", "")
    if not sessionId:
        return

    sessionInfo = CTXG_ReadSessionInfo(sessionId)
    if sessionInfo is None:
        return

    # Stale detection: if transcript was modified AFTER the session file,
    # context likely changed (e.g. /compact) and our info is outdated → skip.
    transcriptPath = hookInput.get("transcript_path", "")
    if transcriptPath and sessionInfo.get("updated_at"):
        try:
            transcriptMtime = Path(transcriptPath).stat().st_mtime
            if transcriptMtime > sessionInfo["updated_at"]:
                return  # session info is stale, let it through
        except OSError:
            pass

    usedPct = sessionInfo.get("used_percentage", 0)
    if usedPct <= 0:
        return

    level = CTXG_Evaluate(usedPct, config, sessionInfo)

    # Effective thresholds (session override or global)
    warnPct = sessionInfo.get("override_warn_pct", config["warn_pct"])
    blockPct = sessionInfo.get("override_block_pct", config["block_pct"])

    # Build token detail string if available
    maxTok = sessionInfo.get("max_tokens", 0)
    totalTok = sessionInfo.get("total_tokens", 0)
    tokDetail = ""
    if maxTok > 0:
        tokDetail = f" ~{totalTok//1000}K/{maxTok//1000}K tokens"

    if event == "UserPromptSubmit":
        # Can block before prompt is processed (cheapest)
        if level == "block":
            print(json.dumps({
                "decision": "block",
                "reason": (
                    f"Context Guard: context at {usedPct}%{tokDetail} "
                    f"(limit: {blockPct}%). "
                    f"Run /compact to continue."
                ),
            }))
        elif level == "warn":
            print(json.dumps({
                "additionalContext": (
                    f"[CONTEXT GUARD] Context at {usedPct}%{tokDetail} "
                    f"(warn: {warnPct}%, block: {blockPct}%). "
                    f"Consider running /compact soon. "
                    f"Briefly mention this to the user."
                ),
                "systemMessage": (
                    f"Context Guard: {usedPct}%{tokDetail} "
                    f"(warn: {warnPct}%, block: {blockPct}%)"
                ),
            }))

    elif event == "PostToolUse":
        # Mid-turn safety net — can only warn, not block
        if level == "block":
            print(json.dumps({
                "additionalContext": (
                    f"[CONTEXT GUARD - URGENT] Context at {usedPct}% "
                    f"(over {blockPct}% limit). "
                    f"STOP current work and ask the user to run /compact immediately."
                ),
                "systemMessage": (
                    f"Context Guard: {usedPct}% - OVER LIMIT"
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
            for f in files[:5]:
                try:
                    info = json.loads(f.read_text(encoding="utf-8"))
                    sid = info.get("session_id", "?")[:8]
                    pct = info.get("used_percentage", 0)
                    age = time.time() - info.get("updated_at", 0)
                    maxTok = info.get("max_tokens", 0)
                    totalTok = info.get("total_tokens", 0)
                    modelId = info.get("model_id", "")
                    tokStr = ""
                    if maxTok > 0:
                        tokStr = f" ({totalTok//1000}K/{maxTok//1000}K)"
                    elif totalTok > 0:
                        tokStr = f" ({totalTok//1000}K/?)"
                    modelStr = f" [{modelId}]" if modelId else ""
                    overrides = ""
                    if "override_warn_pct" in info or "override_block_pct" in info:
                        ow = info.get("override_warn_pct", "-")
                        ob = info.get("override_block_pct", "-")
                        overrides = f" [override: warn={ow}%, block={ob}%]"
                    print(f"  Session {sid}...: {pct}%{tokStr}{modelStr} — {age:.0f}s ago{overrides}")
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
        # Detect scope: set [this|all] warn|block <pct>
        # "set block 20"       → global only
        # "set this block 20"  → current session override only
        # "set all block 20"   → global + clear all session overrides
        scope = "global"
        paramIdx = 1
        if args[1].lower() in ("this", "all"):
            scope = args[1].lower()
            paramIdx = 2
        if len(args) < paramIdx + 2:
            print("Usage: set [this|all] warn|block <pct>")
            return
        param = args[paramIdx].lower()
        if param not in ("warn", "block"):
            print(f"Unknown param: {param}. Use 'warn' or 'block'.")
            return
        rawValue = args[paramIdx + 1].strip()
        # Parse value:
        #   "20%" → percentage
        #   "250K"/"250k" → ktokens → convert to %
        #   "20" (bare number < 100) → percentage (compat)
        #   "250000" (bare number >= 100) → tokens → convert to %
        if rawValue.endswith("%"):
            value = int(rawValue.rstrip("%"))
        elif rawValue.upper().endswith("K"):
            tokValue = int(rawValue[:-1]) * 1000
            maxTok = _getMaxTokensFromSessions()
            if maxTok <= 0:
                print(f"Cannot convert {rawValue} tokens to %: no session with max_tokens found yet.")
                print("Run a prompt first so the statusline populates the context window size.")
                return
            value = round(tokValue / maxTok * 100)
            print(f"  {tokValue//1000}K tokens = {value}% of {maxTok//1000}K context window")
        else:
            bareValue = int(rawValue)
            if bareValue < 100:
                # Bare number < 100 → treat as percentage (backward compat)
                value = bareValue
            else:
                # Bare number >= 100 → treat as tokens
                maxTok = _getMaxTokensFromSessions()
                if maxTok <= 0:
                    print(f"Cannot convert {rawValue} tokens to %: no session with max_tokens found yet.")
                    print("Run a prompt first so the statusline populates the context window size.")
                    return
                value = round(bareValue / maxTok * 100)
                print(f"  {bareValue//1000}K tokens = {value}% of {maxTok//1000}K context window")

        if scope == "this":
            # Current session only — need session_id from env
            sid = os.environ.get("CLAUDE_SESSION_ID", "")
            if not sid:
                # Try to find the most recent session file
                if CONTEXT_SHARE_DIR.exists():
                    files = sorted(CONTEXT_SHARE_DIR.glob("*.json"),
                                   key=lambda f: f.stat().st_mtime, reverse=True)
                    if files:
                        sid = files[0].stem
                if not sid:
                    print("Cannot determine current session. Use 'set' (global) instead.")
                    return
            warnPct = value if param == "warn" else None
            blockPct = value if param == "block" else None
            if CTXG_SetSessionOverride(sid, warnPct=warnPct, blockPct=blockPct):
                print(f"Session {sid[:8]}...: {param} override set to {value}%")
            else:
                print("Failed to set override.")

        elif scope == "all":
            # Global + clear all session overrides
            config = CTXG_LoadConfig()
            if param == "warn":
                config["warn_pct"] = value
            else:
                config["block_pct"] = value
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            # Clear all session overrides
            cleared = 0
            if CONTEXT_SHARE_DIR.exists():
                for sf in CONTEXT_SHARE_DIR.glob("*.json"):
                    try:
                        info = json.loads(sf.read_text(encoding="utf-8"))
                        changed = False
                        if param == "warn" and "override_warn_pct" in info:
                            info.pop("override_warn_pct")
                            changed = True
                        if param == "block" and "override_block_pct" in info:
                            info.pop("override_block_pct")
                            changed = True
                        if changed:
                            with open(sf, "w", encoding="utf-8") as f:
                                json.dump(info, f)
                            cleared += 1
                    except (json.JSONDecodeError, OSError):
                        pass
            print(f"Global {param}: {value}% — cleared {cleared} session override(s)")

        else:
            # Global only
            config = CTXG_LoadConfig()
            if param == "warn":
                config["warn_pct"] = value
            else:
                config["block_pct"] = value
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            print(f"Global {param} threshold: {value}%")

    else:
        print("Usage:")
        print("  /ctxguard status                        — show config + sessions")
        print("  /ctxguard set warn|block <pct>          — set global threshold")
        print("  /ctxguard set this warn|block <pct>     — set for current session only")
        print("  /ctxguard set all warn|block <pct>      — set global + clear all overrides")
        print("  /ctxguard enable|disable                — toggle on/off")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cliMain()
    else:
        hookMain()
