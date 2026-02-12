# Hexcrawler2

Deterministic engine substrate prototype for a hexcrawl simulation.

## Included in this phase
- Axial hex world state keyed by coordinate.
- Per-hex editable records with JSON load/save.
- Deterministic fixed-tick simulation core.
- Smooth entity movement with sub-hex offsets.
- Minimal CLI viewer/controller split.
- Determinism + save/load hash tests.

## Quickstart
```bash
python -m pip install pytest
pytest -q
PYTHONPATH=src python -m hexcrawler.cli.viewer
```
