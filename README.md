# Hexcrawler2

Hexcrawler2 is a deterministic simulation engine substrate for a persistent hexcrawl world, with simulation logic separated from read-only viewer/debug surfaces.

## Current architecture identity
- Deterministic fixed-tick simulation core with seeded RNG and replay/hash stability.
- Persistent serialized world state (including site-local pressure/evidence aftermath substrates).
- Viewer/UI remains read-only with respect to authoritative simulation mutation (commands/events drive changes).

## Canonical run
```bash
python play.py
```

## Canonical test
```bash
PYTHONPATH=src pytest -q
```

## Further reading
- `docs/ARCHITECTURE.md`
- `docs/STATUS.md`
- `AGENTS.md`

## Dependencies
- Viewer/runtime and pygame-backed tests require `pygame` (declared in `requirements.txt`).
- Install locally with:

```bash
python -m pip install -r requirements.txt
```

If your environment blocks the default package index, use an approved mirror and run:

```bash
python -m pip install --index-url <your-approved-index> pygame
```

## Headless smoke
For simulation/viewer startup without a real display/audio device:

```bash
python play.py --headless
```

This launch path sets `SDL_VIDEODRIVER=dummy` and `SDL_AUDIODRIVER=dummy` automatically.

## Manual visual audit (default `core_playable`)
Run:

```bash
python play.py
```

During the first minute, verify:
- player marker readability on campaign map
- Greybridge and Old Stair site visibility
- hostile patrol/danger marker near Old Stair approach
- contact modal appears when patrol contact occurs (fight/flee flow)
- transition overlay appears on campaign→local/return transitions
- local actor distinction (player vs hostile markers)
- floating combat feedback labels in local combat
- HUD action hints are present and role-appropriate

This audit is presentation-only and must not mutate simulation through UI shortcuts outside existing command/event seams.
