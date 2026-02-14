from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hexcrawler.sim.core import Simulation
from hexcrawler.sim.periodic import PeriodicScheduler
from hexcrawler.sim.rules import RuleModule

CHECK_EVENT_TYPE = "check"


class CheckRunner(RuleModule):
    """Generic deterministic check emitter backed by PeriodicScheduler tasks."""

    name = "check_runner"

    def __init__(self) -> None:
        self._checks: dict[str, tuple[int, int]] = {}
        self._registration_order: list[str] = []
        self._callbacks: dict[str, Callable[[Simulation, int], dict[str, Any] | None]] = {}

    def register_check(self, check_name: str, interval_ticks: int, start_tick: int = 0) -> None:
        if not check_name:
            raise ValueError("check_name must be a non-empty string")
        if not isinstance(interval_ticks, int) or interval_ticks <= 0:
            raise ValueError("interval_ticks must be a positive integer")
        if not isinstance(start_tick, int) or start_tick < 0:
            raise ValueError("start_tick must be a non-negative integer")

        existing = self._checks.get(check_name)
        if existing is not None:
            if existing != (interval_ticks, start_tick):
                raise ValueError(
                    f"check {check_name!r} already registered with interval/start {existing}; "
                    f"got {(interval_ticks, start_tick)}"
                )
            return

        self._checks[check_name] = (interval_ticks, start_tick)
        self._registration_order.append(check_name)

    def set_check_callback(
        self,
        check_name: str,
        callback: Callable[[Simulation, int], dict[str, Any] | None],
    ) -> None:
        if check_name not in self._checks:
            raise ValueError(f"cannot set callback for unknown check: {check_name}")
        self._callbacks[check_name] = callback

    def on_simulation_start(self, sim: Simulation) -> None:
        scheduler = sim.get_rule_module(PeriodicScheduler.name)
        if scheduler is None:
            scheduler = PeriodicScheduler()
            sim.register_rule_module(scheduler)
        if not isinstance(scheduler, PeriodicScheduler):
            raise TypeError("periodic_scheduler module must be a PeriodicScheduler")

        for check_name in self._registration_order:
            interval_ticks, start_tick = self._checks[check_name]
            task_name = self._task_name_for_check(check_name)
            scheduler.register_task(task_name=task_name, interval_ticks=interval_ticks, start_tick=start_tick)
            scheduler.set_task_callback(task_name, self._build_callback(check_name, task_name))

    def _task_name_for_check(self, check_name: str) -> str:
        return f"check:{check_name}"

    def _build_callback(self, check_name: str, task_name: str) -> Callable[[Simulation, int], None]:
        def _emit(sim: Simulation, tick: int) -> None:
            callback = self._callbacks.get(check_name)
            meta = callback(sim, tick) if callback is not None else None
            params: dict[str, Any] = {
                "check": check_name,
                "source_task": task_name,
                "tick": tick,
                # Deterministic monotonic sequence derived from serialized simulation state.
                "seq": sim._next_event_counter,
            }
            if meta is not None:
                params["meta"] = meta
            # Schedule for the next tick to avoid same-tick insertion starvation.
            sim.schedule_event_at(tick=tick + 1, event_type=CHECK_EVENT_TYPE, params=params)

        return _emit
