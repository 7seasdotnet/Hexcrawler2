# How to Verify

1. Create and activate a virtual environment:
   - `python -m venv .venv`
   - `source .venv/bin/activate`
2. Install dependencies:
   - `python -m pip install --upgrade pip`
   - `python -m pip install -r requirements.txt`
   - `python -m pip install pytest`
3. Run the game:
   - `python run_game.py`
4. Verify movement behavior in viewer:
   - Hold `W`, `A`, `S`, `D` in any combination and confirm movement is smooth and diagonal is not faster than cardinal.
   - Release all movement keys and confirm motion stops immediately.
   - Right-click on a valid world hex and confirm a small menu appears with `Move Here`.
   - Left-click `Move Here` and confirm the entity moves to that world position and stops at arrival.
   - Right-click outside defined world hexes and confirm no command is issued.
   - Confirm HUD updates `CURRENT HEX`, `ticks`, and `day`.
5. Run tests:
   - `PYTHONPATH=src pytest -q`
