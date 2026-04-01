from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from hexcrawler.cli.pygame_viewer import run_pygame_viewer
from hexcrawler.cli.runtime_profiles import CORE_PLAYABLE, DEFAULT_RUNTIME_PROFILE, RUNTIME_PROFILE_CHOICES, RuntimeProfile
from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, Simulation, WorldState
from hexcrawler.sim.hash import world_hash
from hexcrawler.sim.world import CampaignPatrolRecord

DEFAULT_MAP_PATH = "content/examples/viewer_map.json"
DEFAULT_SAVE_PATH = "saves/canonical_viewer_save.json"
DEFAULT_SEED = 7
CORE_PLAYABLE_MAJOR_SITE_IDS: tuple[str, ...] = ("home_greybridge", "demo_dungeon_entrance")
CORE_PLAYABLE_PATROL_TEMPLATE_ID = "campaign_danger_patrol"
CORE_PLAYABLE_DEFAULT_PATROL_ID = "patrol:core_playable"
CORE_PLAYABLE_DEFAULT_PATROL_WORLD_POSITION: tuple[float, float] = (-2.60, 1.90)
CORE_PLAYABLE_DEFAULT_PATROL_SPEED = 0.14


@dataclass(frozen=True)
class StartupTruth:
    reused_existing_save: bool
    rebuilt_save: bool
    source_map_path: str
    source_save_path: str
    major_site_rows: tuple[str, ...]
    home_town_count: int
    dungeon_entrance_count: int
    patrol_count: int


def _site_row(world: WorldState, site_id: str) -> str:
    site = world.sites.get(site_id)
    if site is None:
        return f"{site_id}:missing"
    return f"{site_id}:{site.site_type}"


def _scene_counts(world: WorldState, sim: Simulation) -> tuple[int, int, int]:
    home_town_count = sum(1 for site in world.sites.values() if site.site_id == "home_greybridge" and site.site_type == "town")
    dungeon_entrance_count = sum(
        1 for site in world.sites.values() if site.site_id == "demo_dungeon_entrance" and site.site_type in {"dungeon", "dungeon_entrance"}
    )
    patrol_count = sum(1 for entity in sim.state.entities.values() if entity.template_id == CORE_PLAYABLE_PATROL_TEMPLATE_ID)
    return home_town_count, dungeon_entrance_count, patrol_count


def _startup_truth_from_world_sim(
    *,
    world: WorldState,
    sim: Simulation,
    map_path: str,
    save_path: str,
    reused_existing_save: bool,
    rebuilt_save: bool,
) -> StartupTruth:
    home_town_count, dungeon_entrance_count, patrol_count = _scene_counts(world, sim)
    return StartupTruth(
        reused_existing_save=reused_existing_save,
        rebuilt_save=rebuilt_save,
        source_map_path=map_path,
        source_save_path=save_path,
        major_site_rows=tuple(_site_row(world, site_id) for site_id in CORE_PLAYABLE_MAJOR_SITE_IDS),
        home_town_count=home_town_count,
        dungeon_entrance_count=dungeon_entrance_count,
        patrol_count=patrol_count,
    )


def _core_playable_scene_valid(world: WorldState, sim: Simulation) -> bool:
    home_town_count, dungeon_entrance_count, patrol_count = _scene_counts(world, sim)
    return home_town_count >= 1 and dungeon_entrance_count >= 1 and patrol_count >= 1


def _seed_core_playable_scene(sim: Simulation) -> None:
    if CORE_PLAYABLE_DEFAULT_PATROL_ID not in sim.state.world.campaign_patrols:
        sim.state.world.campaign_patrols[CORE_PLAYABLE_DEFAULT_PATROL_ID] = CampaignPatrolRecord(
            patrol_id=CORE_PLAYABLE_DEFAULT_PATROL_ID,
            template_id=CORE_PLAYABLE_PATROL_TEMPLATE_ID,
            space_id="overworld",
            spawn_position={"x": CORE_PLAYABLE_DEFAULT_PATROL_WORLD_POSITION[0], "y": CORE_PLAYABLE_DEFAULT_PATROL_WORLD_POSITION[1]},
            route_anchors=[{"x": -1.55, "y": 2.4}, {"x": -3.2, "y": 1.25}],
            label="Old Stair Approach Patrol",
            tags=["core_playable", "patrol"],
        )
    patrol_record = sim.state.world.campaign_patrols[CORE_PLAYABLE_DEFAULT_PATROL_ID]
    patrol = EntityState(
        entity_id=patrol_record.patrol_id,
        position_x=float(patrol_record.spawn_position["x"]),
        position_y=float(patrol_record.spawn_position["y"]),
        speed_per_tick=CORE_PLAYABLE_DEFAULT_PATROL_SPEED,
        template_id=patrol_record.template_id,
        stats={"faction_id": "hostile", "role": "patrol"},
    )
    sim.add_entity(patrol)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python play.py", description="Canonical Hexcrawler launcher.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Seed used when creating the canonical save.")
    parser.add_argument("--load-save", default=DEFAULT_SAVE_PATH, help="Path to canonical save JSON to load at startup.")
    parser.add_argument("--map-path", default=DEFAULT_MAP_PATH, help="Map path used if canonical save must be created.")
    parser.add_argument("--headless", action="store_true", help="Run startup path in headless mode.")
    parser.add_argument(
        "--runtime-profile",
        choices=RUNTIME_PROFILE_CHOICES,
        default=DEFAULT_RUNTIME_PROFILE,
        help="Runtime module composition profile for viewer startup.",
    )
    return parser


def _ensure_save_exists(
    *,
    map_path: str,
    save_path: str,
    seed: int,
    runtime_profile: RuntimeProfile,
    refresh_if_mismatch: bool = False,
) -> StartupTruth:
    save_file = Path(save_path)
    rebuilt = False
    reused = False
    world = load_world_json(map_path)
    should_refresh_for_scene = refresh_if_mismatch and runtime_profile == CORE_PLAYABLE
    if save_file.exists():
        if not refresh_if_mismatch:
            loaded_world, loaded_sim = load_game_json(str(save_file))
            return _startup_truth_from_world_sim(
                world=loaded_world,
                sim=loaded_sim,
                map_path=map_path,
                save_path=save_path,
                reused_existing_save=True,
                rebuilt_save=False,
            )
        refresh_required = True
        try:
            saved_world, saved_sim = load_game_json(str(save_file))
            scene_valid = _core_playable_scene_valid(saved_world, saved_sim) if should_refresh_for_scene else True
            refresh_required = world_hash(saved_world) != world_hash(world) or not scene_valid
        except Exception:
            refresh_required = True
        if not refresh_required:
            reused = True
            loaded_world, loaded_sim = load_game_json(str(save_file))
            return _startup_truth_from_world_sim(
                world=loaded_world,
                sim=loaded_sim,
                map_path=map_path,
                save_path=save_path,
                reused_existing_save=reused,
                rebuilt_save=rebuilt,
            )
    save_file.parent.mkdir(parents=True, exist_ok=True)
    simulation = Simulation(world=world, seed=seed)
    if runtime_profile == CORE_PLAYABLE:
        _seed_core_playable_scene(simulation)
    save_game_json(save_file, world, simulation)
    rebuilt = True
    return _startup_truth_from_world_sim(
        world=world,
        sim=simulation,
        map_path=map_path,
        save_path=save_path,
        reused_existing_save=reused,
        rebuilt_save=rebuilt,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    refresh_if_mismatch = (
        args.runtime_profile == CORE_PLAYABLE and args.load_save == DEFAULT_SAVE_PATH and args.map_path == DEFAULT_MAP_PATH
    )
    startup_truth = _ensure_save_exists(
        map_path=args.map_path,
        save_path=args.load_save,
        seed=args.seed,
        runtime_profile=args.runtime_profile,
        refresh_if_mismatch=refresh_if_mismatch,
    )
    print(
        "[hexcrawler.play] startup_truth "
        f"runtime_profile={args.runtime_profile} "
        f"map_path={startup_truth.source_map_path} "
        f"save_path={startup_truth.source_save_path} "
        f"save_action={'rebuilt' if startup_truth.rebuilt_save else 'reused'} "
        f"major_sites={','.join(startup_truth.major_site_rows)} "
        f"home_town_count={startup_truth.home_town_count} "
        f"dungeon_entrance_count={startup_truth.dungeon_entrance_count} "
        f"hostile_patrol_count={startup_truth.patrol_count}"
    )
    return run_pygame_viewer(
        map_path=args.map_path,
        runtime_profile=args.runtime_profile,
        headless=args.headless,
        load_save=args.load_save,
        save_path=args.load_save,
    )


if __name__ == "__main__":
    raise SystemExit(main())
