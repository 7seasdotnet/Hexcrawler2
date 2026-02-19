from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hexcrawler.sim.core import SimCommand, SimEvent, Simulation


class RuleModule:
    """Deterministic simulation rule-module substrate.

    Rule modules are registered on a ``Simulation`` instance and are executed in
    stable registration order for every lifecycle hook.
    """

    name: str

    def on_simulation_start(self, sim: Simulation) -> None:
        """Called once, immediately when the module is registered."""

    def on_tick_start(self, sim: Simulation, tick: int) -> None:
        """Called at the start of each authoritative simulation tick."""

    def on_tick_end(self, sim: Simulation, tick: int) -> None:
        """Called at the end of each authoritative simulation tick."""


    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        """Called for each command at its scheduled tick; return True when handled."""
        return False

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        """Called after each event is executed on its scheduled tick."""

