# How to Verify

1. Create and activate a virtual environment:
   - `python -m venv .venv`
   - `source .venv/bin/activate`
2. Install dependencies:
   - `python -m pip install --upgrade pip`
   - `python -m pip install -r requirements.txt`
   - `python -m pip install pytest`
3. Run the game (single clean command from repo root):
   - `python run_game.py`
4. Move the entity with keyboard:
   - Use `W`, `A`, `S`, `D`.
   - Confirm HUD updates `CURRENT HEX`, `ticks`, and `day`.
5. Run tests:
   - `PYTHONPATH=src pytest -q`
