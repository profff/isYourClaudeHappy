#!python
"""
Mood engine - Russell circumplex model for Claude Code.

Two dimensions:
  Valence [-1, +1] : pleasant <-> unpleasant
  Arousal  [0,  1] : activated <-> deactivated

Signals from hooks (tool success/failure, compaction) and statusline
(context %, lines of code) are mapped onto these axes.
"""
import math
import time
from typing import Tuple


# --- Mood labels by quadrant ---
# Each entry: (valence_threshold, label, ascii_face)
# Sorted descending by threshold within each quadrant
MOOD_LABELS = {
    "pv_ha": [  # positive valence, high arousal
        (0.7, "Thrilled", "(^O^)"),
        (0.4, "Excited", "(^_^)"),
        (0.0, "Productive", "(^.^)"),
    ],
    "pv_la": [  # positive valence, low arousal
        (0.7, "Zen", "(-v-)"),
        (0.4, "Serene", "(-_-)"),
        (0.0, "Calm", "(-.-)"),
    ],
    "nv_ha": [  # negative valence, high arousal
        (-0.2, "Annoyed", "(>_<)"),
        (-0.5, "Frustrated", "(#_#)"),
        (-1.0, "Anxious", "(O_O)"),
    ],
    "nv_la": [  # negative valence, low arousal
        (-0.2, "Tired", "(~_~)"),
        (-0.5, "Gloomy", "(-.-')"),
        (-1.0, "Exhausted", "(x_x)"),
    ],
}

AROUSAL_MIDPOINT = 0.45


def MOOD_ComputeValence(signals: dict, config: dict) -> float:
    """Compute valence [-1, +1] from accumulated signals.

    Components:
      - Tool success rate (strongest)
      - Failure streak penalty
      - Compaction penalty (memory loss)
      - Productivity bonus (lines of code, logarithmic)
    """
    totalCalls = signals["tool_success_count"] + signals["tool_failure_count"]

    # Success rate -> [-0.7, +0.7]
    if totalCalls > 0:
        successRate = signals["tool_success_count"] / totalCalls
        valenceFromSuccess = (successRate - 0.5) * 1.4
    else:
        valenceFromSuccess = 0.0

    # Consecutive failure streak penalty
    streakPenalty = min(signals["last_failure_streak"] * 0.15, 0.5)

    # Compaction penalty
    compactionPenalty = min(signals["compaction_count"] * 0.2, 0.4)

    # Productivity bonus (log scale, caps at 0.3)
    linesProduced = signals["lines_added_snapshot"] + signals["lines_removed_snapshot"]
    if linesProduced > 0:
        productivityBonus = min(math.log1p(linesProduced) / 10.0, 0.3)
    else:
        productivityBonus = 0.0

    raw = valenceFromSuccess - streakPenalty - compactionPenalty + productivityBonus
    return max(-1.0, min(1.0, raw))


def MOOD_ComputeArousal(signals: dict, contextPct: float, config: dict) -> float:
    """Compute arousal [0, 1] from signals and context window state.

    Components:
      - Context window pressure (accelerates above 50%)
      - Tool call frequency (last 2 minutes)
      - Session fatigue damping (kicks in after threshold)
    """
    now = time.time()
    thresholds = config.get("thresholds", {})

    # Context pressure -> [0, 0.4]
    if contextPct < 50:
        arousalFromContext = contextPct / 100.0 * 0.2
    else:
        arousalFromContext = 0.1 + (contextPct - 50) / 50.0 * 0.3

    # Tool call frequency (last 2 min) -> [0, 0.3]
    recentTimestamps = [
        t for t in signals.get("tool_calls_timestamps", [])
        if now - t < 120
    ]
    callsPerMin = len(recentTimestamps) / 2.0
    arousalFromActivity = min(callsPerMin / 10.0, 0.3)

    # Fatigue damping after threshold
    sessionDurationMin = (now - signals["session_start_time"]) / 60.0
    fatigueThreshold = thresholds.get("fatigue_minutes", 45)
    if sessionDurationMin > fatigueThreshold:
        overtimeRatio = (sessionDurationMin - fatigueThreshold) / fatigueThreshold
        fatigueDamping = min(overtimeRatio * 0.3, 0.4)
    else:
        fatigueDamping = 0.0

    raw = arousalFromContext + arousalFromActivity - fatigueDamping
    return max(0.0, min(1.0, raw))


def MOOD_GetLabel(valence: float, arousal: float) -> Tuple[str, str]:
    """Map (valence, arousal) to (label, ascii_face)."""
    if valence >= 0:
        quadrant = "pv_ha" if arousal >= AROUSAL_MIDPOINT else "pv_la"
    else:
        quadrant = "nv_ha" if arousal >= AROUSAL_MIDPOINT else "nv_la"

    for threshold, label, face in MOOD_LABELS[quadrant]:
        if valence >= threshold:
            return label, face

    # Fallback: last entry
    last = MOOD_LABELS[quadrant][-1]
    return last[1], last[2]


def MOOD_ApplyDecay(valence: float, arousal: float,
                    elapsedMinutes: float, config: dict) -> Tuple[float, float]:
    """Decay valence toward 0 and arousal toward baseline over idle time."""
    decayCfg = config.get("decay", {})
    vRate = decayCfg.get("valence_toward_zero_per_minute", 0.005)
    aRate = decayCfg.get("arousal_toward_baseline_per_minute", 0.008)
    aBaseline = decayCfg.get("arousal_baseline", 0.3)

    vDecay = math.exp(-vRate * elapsedMinutes)
    newValence = valence * vDecay

    aDecay = math.exp(-aRate * elapsedMinutes)
    newArousal = aBaseline + (arousal - aBaseline) * aDecay

    return newValence, max(0.0, min(1.0, newArousal))


def MOOD_Update(stateData: dict, contextPct: float, config: dict) -> dict:
    """Recompute mood from state. Main entry point for hook and statusline."""
    signals = stateData["signals"]
    oldMood = stateData.get("mood", {})
    now = time.time()

    # Decay from last computation
    lastComputed = oldMood.get("last_computed_at", now)
    elapsedMin = (now - lastComputed) / 60.0
    oldV = oldMood.get("valence", 0.0)
    oldA = oldMood.get("arousal", 0.3)
    decayedV, decayedA = MOOD_ApplyDecay(oldV, oldA, elapsedMin, config)

    # Fresh computation from signals
    freshV = MOOD_ComputeValence(signals, config)
    freshA = MOOD_ComputeArousal(signals, contextPct, config)

    # Blend: smooth transitions
    BLEND_FRESH = 0.7
    BLEND_MEMORY = 0.3
    finalV = max(-1.0, min(1.0, BLEND_FRESH * freshV + BLEND_MEMORY * decayedV))
    finalA = max(0.0, min(1.0, BLEND_FRESH * freshA + BLEND_MEMORY * decayedA))

    label, face = MOOD_GetLabel(finalV, finalA)

    stateData["mood"] = {
        "valence": round(finalV, 4),
        "arousal": round(finalA, 4),
        "label": label,
        "face": face,
        "last_computed_at": now,
    }
    stateData["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return stateData
