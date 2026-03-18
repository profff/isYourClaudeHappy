---
allowed-tools: Bash(python:*), Read, Edit
argument-hint: [on|off|context|status|set|reset|dump]
description: Controle de la jauge d'humeur Claude Code
---

# Mood Gauge - Controle

Gere la jauge d'humeur affichee dans la statusline de Claude Code.

## Commandes disponibles

| Commande | Description |
|----------|-------------|
| `/mood` ou `/mood status` | Afficher l'etat actuel (mood, signaux, config) |
| `/mood on` | Activer le mode full (hooks + statusline) |
| `/mood off` | Desactiver completement la jauge |
| `/mood context` | Mode contexte seul : barre + tokens + guard, sans mood |
| `/mood set <param> <value>` | Modifier un seuil ou parametre |
| `/mood reset` | Remettre la session a zero (RAZ des compteurs) |
| `/mood dump` | Afficher le state JSON brut de la session |
| `/mood install` | Installer les hooks dans settings.json |
| `/mood uninstall` | Desinstaller les hooks de settings.json |

## Parametres ajustables via `/mood set`

| Parametre | Description | Defaut |
|-----------|-------------|--------|
| `fatigue <min>` | Seuil de fatigue en minutes | 45 |
| `context_warning <pct>` | Seuil d'alerte contexte (%) | 70 |
| `context_critical <pct>` | Seuil critique contexte (%) | 85 |
| `bar_width <n>` | Largeur de la barre | 6 |
| `decay_valence <rate>` | Vitesse de retour a zero de la valence | 0.005 |
| `decay_arousal <rate>` | Vitesse de retour au baseline de l'arousal | 0.008 |
| `color <on\|off>` | Activer/desactiver les couleurs ANSI | on |

## Execution

Le fichier de configuration est : `D:/Dev/AI_Bridge/CLAUDE_FEELINGS/mood/config.json`
Le dossier des sessions est : `D:/Dev/AI_Bridge/CLAUDE_FEELINGS/mood/data/sessions/`
Le script setup est : `D:/Dev/AI_Bridge/CLAUDE_FEELINGS/mood/mood_setup.py`

### Pour `/mood status` (defaut)
1. Lire `D:/Dev/AI_Bridge/CLAUDE_FEELINGS/mood/config.json` et afficher le mode actuel
2. Chercher le fichier session le plus recent dans `data/sessions/` et afficher :
   - Mood actuel (face + label + valence + arousal)
   - Signaux accumules (tool success/failure, compaction count, prompt count)
   - Config active (mode, seuils)

### Pour `/mood on`, `/mood off`, `/mood context`
Editer `D:/Dev/AI_Bridge/CLAUDE_FEELINGS/mood/config.json` : changer `"mode"` en `"full"`, `"off"`, ou `"context"`.
Confirmer le changement a l'utilisateur.

### Pour `/mood set <param> <value>`
Editer `D:/Dev/AI_Bridge/CLAUDE_FEELINGS/mood/config.json` selon le parametre :
- `fatigue` → `thresholds.fatigue_minutes`
- `context_warning` → `thresholds.context_warning`
- `context_critical` → `thresholds.context_critical`
- `bar_width` → `display.bar_width`
- `decay_valence` → `decay.valence_toward_zero_per_minute`
- `decay_arousal` → `decay.arousal_toward_baseline_per_minute`
- `color on` → `display.color_enabled` = true
- `color off` → `display.color_enabled` = false

### Pour `/mood reset`
Supprimer tous les fichiers `*.json` dans `D:/Dev/AI_Bridge/CLAUDE_FEELINGS/mood/data/sessions/`.
La prochaine action recreera automatiquement un state frais.

### Pour `/mood dump`
Lire et afficher le contenu JSON du fichier session le plus recent dans `data/sessions/`.

### Pour `/mood install` et `/mood uninstall`
Run: `python "D:/Dev/AI_Bridge/CLAUDE_FEELINGS/mood/mood_setup.py" $ARGUMENTS`
