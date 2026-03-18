#!python
"""
Claude Code statusline script for mood gauge.
Reads JSON from stdin (Claude Code session data) + per-session state file.
Outputs ANSI-formatted mood display.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Force UTF-8 output (Windows defaults to cp1252 which chokes on block chars)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from mood_config import MCFG_Load
from mood_engine import MOOD_Update

DATA_DIR = SCRIPT_DIR / "data" / "sessions"

# ANSI escape codes
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_DIM = "\033[2m"
C_RESET = "\033[0m"


CONTEXT_SHARE_DIR = Path.home() / ".claude" / "context_guard"


def _shareContextInfo(ctxWindow: dict, sessionId: str, modelId: str = ""):
    """Write context info to per-session file for Context Guard hook."""
    if not ctxWindow or not sessionId:
        return
    try:
        CONTEXT_SHARE_DIR.mkdir(parents=True, exist_ok=True)
        sharePath = CONTEXT_SHARE_DIR / f"{sessionId}.json"
        # Preserve existing overrides from context guard
        existing = {}
        if sharePath.exists():
            try:
                with open(sharePath, encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        totalTokens = (ctxWindow.get("total_input_tokens", 0) or 0) + \
                      (ctxWindow.get("total_output_tokens", 0) or 0)
        info = {
            "session_id": sessionId,
            "used_percentage": ctxWindow.get("used_percentage", 0),
            "total_tokens": totalTokens,
            "max_tokens": ctxWindow.get("context_window_size", 0) or 0,
            "model_id": modelId,
            "updated_at": time.time(),
        }
        # Keep session overrides
        for key in ("override_warn_pct", "override_block_pct"):
            if key in existing:
                info[key] = existing[key]
        # Atomic write
        fd, tmpPath = tempfile.mkstemp(suffix=".tmp",
                                       dir=str(CONTEXT_SHARE_DIR))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(info, f)
        os.replace(tmpPath, str(sharePath))
    except Exception:
        pass


def SL_BuildBar(pct: float, width: int, color: bool,
                 warnPct: float = 0, blockPct: float = 0) -> str:
    """Build a colored progress bar with warn/block markers."""
    filled = max(0, min(width, round(pct / 100.0 * width)))
    empty = width - filled

    if color:
        if blockPct and pct >= blockPct:
            c = C_RED
        elif warnPct and pct >= warnPct:
            c = C_YELLOW
        elif pct >= 85:
            c = C_RED
        elif pct >= 60:
            c = C_YELLOW
        else:
            c = C_GREEN

        # Build bar with warn/block markers
        bar = []
        warnPos = round(warnPct / 100.0 * width) if warnPct else -1
        blockPos = round(blockPct / 100.0 * width) if blockPct else -1
        for i in range(width):
            if i == blockPos:
                bar.append(f"{C_RED}|{C_RESET}")
            elif i == warnPos:
                bar.append(f"{C_YELLOW}|{C_RESET}")
            elif i < filled:
                bar.append(f"{c}█{C_RESET}")
            else:
                bar.append("░")
        return "".join(bar)
    return f"{'#' * filled}{'.' * empty}"




def SL_RenderFull(sessionId: str, contextPct: int, statusData: dict,
                  config: dict, guardBlockPct: float = 0) -> tuple[str, str]:
    """Full mode: read state file, recompute mood with real context%."""
    face, label = "(-.-)", "Calm"
    if not sessionId:
        return face, label

    statePath = DATA_DIR / f"{sessionId}.json"
    try:
        if not statePath.exists():
            return face, label

        with open(statePath, "r", encoding="utf-8") as f:
            stateData = json.load(f)

        # Inject lines snapshot from statusline data
        cost = statusData.get("cost", {})
        stateData["signals"]["lines_added_snapshot"] = cost.get(
            "total_lines_added", 0) or 0
        stateData["signals"]["lines_removed_snapshot"] = cost.get(
            "total_lines_removed", 0) or 0

        # Inject guard block threshold for arousal normalization
        stateData["signals"]["guard_block_pct"] = guardBlockPct

        stateData = MOOD_Update(stateData, contextPct, config)
        face = stateData["mood"]["face"]
        label = stateData["mood"]["label"]

        # Save back (statusline has the freshest context data)
        # Throttle writes to at most 1/s
        lastMod = statePath.stat().st_mtime
        if time.time() - lastMod > 1.0:
            try:
                fd, tmpPath = tempfile.mkstemp(
                    dir=str(DATA_DIR), suffix=".tmp")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(stateData, f, indent=2)
                os.replace(tmpPath, str(statePath))
            except Exception:
                pass
    except Exception:
        pass

    return face, label


def SL_CleanupOldSessions(maxAgeHours: int):
    """Remove session state files older than maxAgeHours. Lazy, runs rarely."""
    sentinelPath = DATA_DIR / ".last_cleanup"
    try:
        if sentinelPath.exists():
            if time.time() - sentinelPath.stat().st_mtime < 3600:
                return  # Already cleaned up in the last hour
        cutoff = time.time() - maxAgeHours * 3600
        for f in DATA_DIR.glob("*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass
        sentinelPath.touch()
    except Exception:
        pass


def SL_Render(statusData: dict, config: dict) -> str:
    """Produce the final statusline string."""
    mode = config.get("mode", "full")
    if mode == "off":
        return ""

    display = config.get("display", {})
    barWidth = display.get("bar_width", 6)
    showContext = display.get("show_context", True)
    showLabel = display.get("show_label", True)
    colorEnabled = display.get("color_enabled", True)

    # Extract context%
    ctxWindow = statusData.get("context_window", {})
    rawPct = ctxWindow.get("used_percentage")
    contextPct = int(rawPct) if rawPct is not None else 0

    # Share context info for Context Guard hook
    modelInfo = statusData.get("model", {})
    modelId = modelInfo.get("id", "") if isinstance(modelInfo, dict) else ""
    _shareContextInfo(ctxWindow, statusData.get("session_id", ""), modelId)

    sessionId = statusData.get("session_id", "")

    # Read guard thresholds for this session
    warnPct, blockPct = 0, 0
    if sessionId:
        guardPath = CONTEXT_SHARE_DIR / f"{sessionId}.json"
        try:
            if guardPath.exists():
                with open(guardPath, encoding="utf-8") as f:
                    guardInfo = json.load(f)
                guardCfgPath = Path.home() / ".claude" / "context_guard.json"
                globalCfg = {}
                if guardCfgPath.exists():
                    with open(guardCfgPath, encoding="utf-8") as f:
                        globalCfg = json.load(f)
                warnPct = guardInfo.get("override_warn_pct", globalCfg.get("warn_pct", 0))
                blockPct = guardInfo.get("override_block_pct", globalCfg.get("block_pct", 0))
        except (json.JSONDecodeError, OSError):
            pass

    # Context-only mode: just the bar + tokens, no mood
    if mode == "context":
        bar = SL_BuildBar(contextPct, barWidth, colorEnabled, warnPct, blockPct)
        # Build token detail
        maxTok = ctxWindow.get("context_window_size", 0) or 0
        totalInputTok = ctxWindow.get("total_input_tokens", 0) or 0
        totalOutputTok = ctxWindow.get("total_output_tokens", 0) or 0
        totalTok = totalInputTok + totalOutputTok
        tokStr = ""
        if maxTok > 0:
            tokStr = f" {totalTok//1000}K/{maxTok//1000}K"
        guardStr = ""
        if warnPct or blockPct:
            guardStr = f" w{warnPct}b{blockPct}"
        ctxStr = f"ctx {contextPct}%{tokStr}{guardStr}"
        if colorEnabled:
            return f"[{bar}] {C_DIM}{ctxStr}{C_RESET}"
        return f"[{bar}] {ctxStr}"

    face, label = SL_RenderFull(sessionId, contextPct, statusData, config,
                                 guardBlockPct=blockPct)

    # Assemble output
    bar = SL_BuildBar(contextPct, barWidth, colorEnabled, warnPct, blockPct)
    parts = [face, f"[{bar}]"]
    if showLabel:
        parts.append(f"{label:<13}")
    if showContext:
        guardStr = ""
        if warnPct or blockPct:
            guardStr = f" w{warnPct}b{blockPct}"
        ctxStr = f"ctx {contextPct}%{guardStr}"
        if colorEnabled:
            parts.append(f"{C_DIM}| {ctxStr}{C_RESET}")
        else:
            parts.append(f"| {ctxStr}")

    return " ".join(parts)


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    config = MCFG_Load()

    # Lazy cleanup of old sessions
    cleanupHours = config.get("cleanup", {}).get("max_session_age_hours", 48)
    SL_CleanupOldSessions(cleanupHours)

    output = SL_Render(data, config)
    if output:
        print(output)


if __name__ == "__main__":
    main()
