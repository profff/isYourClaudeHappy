#!python
"""Configuration loader for mood gauge. Pure stdlib."""
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"

DEFAULT_CONFIG = {
    "mode": "full",
    "display": {
        "bar_width": 20,
        "show_context": True,
        "show_label": True,
        "color_enabled": True,
    },
    "thresholds": {
        "context_warning": 70,
        "context_critical": 85,
        "fatigue_minutes": 45,
        "failure_streak_threshold": 3,
    },
    "decay": {
        "valence_toward_zero_per_minute": 0.005,
        "arousal_toward_baseline_per_minute": 0.008,
        "arousal_baseline": 0.3,
    },
    "cleanup": {
        "max_session_age_hours": 48,
    },
}


def MCFG_Load() -> dict:
    """Load config.json with defaults fallback."""
    config = {k: (dict(v) if isinstance(v, dict) else v)
              for k, v in DEFAULT_CONFIG.items()}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                userCfg = json.load(f)
            for key, val in userCfg.items():
                if key.startswith("_"):
                    continue
                if isinstance(val, dict) and key in config and isinstance(config[key], dict):
                    config[key].update(val)
                else:
                    config[key] = val
        except Exception:
            pass
    return config


def MCFG_GetMode() -> str:
    """Quick mode check without full config overhead."""
    return MCFG_Load().get("mode", "full")
