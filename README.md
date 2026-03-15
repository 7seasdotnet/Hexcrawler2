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
