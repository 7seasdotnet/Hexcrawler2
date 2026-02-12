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
6. Verify deterministic topology generation API:
   - `PYTHONPATH=src pytest -q tests/test_world_generation.py`
   - Optional direct check:
     - `PYTHONPATH=src python - <<'PY'`
     - `from hexcrawler.sim.hash import world_hash`
     - `from hexcrawler.sim.world import WorldState`
     - `a = WorldState.create_with_topology(42, 'hex_disk', {'radius': 4})`
     - `b = WorldState.create_with_topology(42, 'hex_disk', {'radius': 4})`
     - `print(world_hash(a) == world_hash(b))`
     - `PY`
7. Save/load serialization contract verification (schema v1 + hash + topology fields):
   - Save a world from code:
     - `PYTHONPATH=src python - <<'PY'`
     - `from hexcrawler.content.io import load_world_json, save_world_json`
     - `w = load_world_json('content/examples/basic_map.json')`
     - `save_world_json('tmp_world.json', w)`
     - `PY`
   - Inspect the output file and confirm top-level `schema_version`, `world_hash`, `topology_type`, and `topology_params`.
   - Load it back and confirm no exception is raised:
     - `PYTHONPATH=src python - <<'PY'`
     - `from hexcrawler.content.io import load_world_json`
     - `load_world_json('tmp_world.json')`
     - `print('ok')`
     - `PY`
   - Hash verification behavior: if you edit `tmp_world.json` content without updating `world_hash`, `load_world_json(...)` fails fast with `ValueError` describing a world hash mismatch.
