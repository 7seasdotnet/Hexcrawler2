# How to Run

1. Install test dependency:
   - `python -m pip install pytest`
2. Run tests:
   - `pytest -q`
3. Launch demo viewer:
   - `PYTHONPATH=src python -m hexcrawler.cli.viewer`

# How to Verify

1. Start demo:
   - `PYTHONPATH=src python -m hexcrawler.cli.viewer`
2. Confirm initial output includes:
   - `tick=0 day=0`
   - Hex rows with terrain and site markers (`T` for town, `D` for dungeon).
3. Issue movement command:
   - `goto 1 -1`
4. Advance time:
   - `tick 20`
5. Confirm entity line shows changing offsets and/or new hex coordinate.
6. Advance a day:
   - `day 1`
7. Confirm day counter increments deterministically.
8. Validate save/load hash behavior via tests:
   - `pytest -q tests/test_save_load.py`
