from __future__ import annotations

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.movement import axial_to_world_xy
from hexcrawler.sim.world import HexCoord

SITE_GLYPHS = {"none": ".", "town": "T", "dungeon": "D"}


class AsciiViewer:
    """Read-only projection of simulation state for terminal display."""

    def render(self, sim: Simulation) -> str:
        lines: list[str] = []
        lines.append(f"tick={sim.state.tick} day={sim.get_day_index()}")

        coords = sorted(sim.state.world.hexes.keys(), key=lambda c: (c.r, c.q))
        if not coords:
            return "\n".join(lines + ["<empty world>"])

        by_row: dict[int, list[str]] = {}
        for coord in coords:
            record = sim.state.world.hexes[coord]
            site = SITE_GLYPHS.get(record.site_type, "?")
            by_row.setdefault(coord.r, []).append(f"({coord.q:>2},{coord.r:>2}) {record.terrain_type[:3]} {site}")

        for r in sorted(by_row):
            lines.append(f"r={r:>2}: " + " | ".join(by_row[r]))

        for entity in sorted(sim.state.entities.values(), key=lambda e: e.entity_id):
            lines.append(
                f"entity[{entity.entity_id}] hex=({entity.hex_coord.q},{entity.hex_coord.r}) "
                f"pos=({entity.position_x:.2f},{entity.position_y:.2f}) target={entity.target_position}"
            )

        return "\n".join(lines)


class SimulationController:
    """Small command adapter; issues commands to sim but does not own state."""

    def __init__(self, sim: Simulation) -> None:
        self.sim = sim

    def set_destination(self, entity_id: str, q: int, r: int) -> None:
        destination = HexCoord(q, r)
        if self.sim.state.world.get_hex_record(destination) is None:
            return
        world_x, world_y = axial_to_world_xy(destination)
        self.sim.append_command(
            SimCommand(
                tick=self.sim.state.tick,
                entity_id=entity_id,
                command_type="set_target_position",
                params={"x": world_x, "y": world_y},
            )
        )

    def advance_ticks(self, ticks: int) -> None:
        self.sim.advance_ticks(ticks)

    def advance_days(self, days: int) -> None:
        self.sim.advance_days(days)


def run_demo(map_path: str = "content/examples/basic_map.json") -> None:
    world = load_world_json(map_path)
    sim = Simulation(world=world, seed=7)
    sim.add_entity(EntityState.from_hex(entity_id="scout", hex_coord=HexCoord(0, 0), speed_per_tick=0.2))

    view = AsciiViewer()
    controller = SimulationController(sim)

    print("Hexcrawler demo. Commands: show | goto <q> <r> | tick <n> | day <n> | quit")
    print(view.render(sim))

    while True:
        raw = input("> ").strip()
        if raw in {"quit", "exit"}:
            break
        if raw == "show":
            print(view.render(sim))
            continue

        parts = raw.split()
        if len(parts) == 3 and parts[0] == "goto":
            controller.set_destination("scout", int(parts[1]), int(parts[2]))
            print("destination set")
            continue
        if len(parts) == 2 and parts[0] == "tick":
            controller.advance_ticks(int(parts[1]))
            print(view.render(sim))
            continue
        if len(parts) == 2 and parts[0] == "day":
            controller.advance_days(int(parts[1]))
            print(view.render(sim))
            continue

        print("unknown command")


if __name__ == "__main__":
    run_demo()
