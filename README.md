# Claude Mood Gauge

A mood indicator for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that displays in the statusline, based on Russell's Circumplex Model of Affect (Valence x Arousal).

Observable signals from your coding session (tool success/failure rate, context window saturation, productivity, compaction events) are mapped onto two psychological dimensions to produce a simulated mood state displayed in real time.

```
(^_^) [████░░] Enthousiaste | ctx 23%     <- things are going well
(-_-) [███░░░] Concentre    | ctx 58%     <- steady work
(>_<) [█████░] Sature       | ctx 87%     <- context window pressure
(~_~) [██░░░░] Fatigue      | ctx 45%     <- long session, low activity
(O_O) [████░░] Anxieux      | ctx 62%     <- lots of tool failures
```

## How it works

**Two dimensions from Russell's model:**

|  | High Arousal | Low Arousal |
|---|---|---|
| **Positive Valence** | Survolte, Enthousiaste, Productif | Zen, Serein, Calme |
| **Negative Valence** | Agace, Frustre, Anxieux | Fatigue, Morose, Epuise |

**Valence** (pleasant <-> unpleasant) is driven by:
- Tool call success/failure ratio (strongest signal)
- Lines of code produced (log scale bonus)
- Consecutive failure streaks (penalty)
- Context compaction events (penalty — "memory loss")

**Arousal** (activated <-> deactivated) is driven by:
- Context window usage % (accelerates above 50%)
- Tool call frequency over last 2 minutes
- Session duration beyond fatigue threshold (damping)

Mood transitions are smoothed with exponential decay and blending (70% fresh + 30% previous state).

## Installation

### Requirements
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Python 3.10+

### Quick install

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/claude-mood-gauge.git
cd claude-mood-gauge

# Install hooks + statusline into Claude Code settings
python mood/mood_setup.py install

# Restart Claude Code
```

That's it. The mood gauge will appear in your statusline.

### Uninstall

```bash
python mood/mood_setup.py uninstall
# Restart Claude Code
```

Your other hooks (nectime, etc.) are preserved during install/uninstall.

## Three modes

Edit `mood/config.json` to switch modes — no need to touch `settings.json`:

| Mode | Description |
|------|-------------|
| `"full"` | Hooks track tool success/failure, compaction, prompts. Full Russell model. |
| `"basic"` | Statusline only, no hooks. Simple heuristic based on context %. |
| `"off"` | Everything disabled. Hooks are no-ops, statusline is blank. |

If you have the `/mood` skill installed, you can also use:
- `/mood on` / `/mood off` / `/mood basic`
- `/mood set fatigue 60` — adjust fatigue threshold
- `/mood status` — see current mood and signals
- `/mood reset` — clear session counters

## Configuration

`mood/config.json`:

```json
{
    "mode": "full",
    "display": {
        "bar_width": 6,
        "show_context": true,
        "show_label": true,
        "color_enabled": true
    },
    "thresholds": {
        "context_warning": 70,
        "context_critical": 85,
        "fatigue_minutes": 45,
        "failure_streak_threshold": 3
    },
    "decay": {
        "valence_toward_zero_per_minute": 0.005,
        "arousal_toward_baseline_per_minute": 0.008,
        "arousal_baseline": 0.3
    }
}
```

## Architecture

```
mood/
  mood_config.py      # Config loader with defaults
  mood_engine.py      # Russell model: valence/arousal computation, quadrant mapping, decay
  mood_hook.py        # Hook handler (PostToolUse, PostToolUseFailure, PreCompact, UserPromptSubmit)
  mood_statusline.py  # Statusline renderer (reads Claude Code JSON + session state)
  mood_setup.py       # Install/uninstall hooks in settings.json
  config.json         # User preferences
  data/sessions/      # Per-session state files (gitignored)
```

**Data flow:**
```
Hook events ──> mood_hook.py ──> data/sessions/{session_id}.json
                                          |
Statusline tick ──> mood_statusline.py ───┘──> ANSI output
                    (reads stdin JSON +
                     session state file)
```

## Optional: `/mood` slash command

Copy `mood.md` to your Claude Code commands directory:

```bash
cp mood.md ~/.claude/commands/mood.md
```

This gives you `/mood status`, `/mood on`, `/mood off`, `/mood set ...`, etc.

## License

MIT
