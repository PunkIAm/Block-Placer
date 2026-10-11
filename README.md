# Block Placer

A Minecraft-like voxel block game in a single-file Python + Pygame.

Handcrafted Cubic-Odyssey-style map, GTA-style third-person camera,
painterly HUD, procedural-ish terrain with biomes, day-time lighting,
mining/placing, a progression tool tier system, quests, and a hidden
secret chest.

## Features

- Single-file engine (`main.py`)
- GTA-style third-person camera + optional first-person (F)
- Handcrafted village, lighthouse, and beacon
- Block mining (hold RMB), placing (E / LMB), grabbing
- 11 block types, 3 tool tiers, XP / leveling, quests
- Secret chest in the cottage (mine the hidden floor)

## Run

```
python3 main.py
```

Requires Python 3.x and Pygame.

## Self-test / frame render (no display needed)

```
python3 main.py selftest        # runs a headless frame + world checks
python3 main.py frames N         # renders N frames
```

## Files

- `main.py` — the game
- `cloud.png` — painted cloud sprite used by the sky
