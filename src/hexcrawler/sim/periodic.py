from __future__ import annotations

from collections.abc import Callable

from hexcrawler.sim.core import SimEvent, Simulation
from hexcrawler.sim.rules import RuleModule

PERIODIC_EVENT_TYPE = "periodic_tick"


class PeriodicScheduler(RuleModule):
    """Generic deterministic periodic scheduling substrate backed by SimEvents."""

    name = "periodic_scheduler"

    def __init__(self) -> None:
        self._sim: Simulation | None = None
        self._task_intervals: dict[str, int] = {}
        self._task_start_ticks: dict[str, int] = {}
        self._registration_order: list[str] = []
        self._callbacks: dict[str, Callable[[Simulation, int], None]] = {}

    def register_task(self, *, task_name: str, interval_ticks: int, start_tick: int = 0) -> None:
        if not task_name:
            raise ValueError("task_name must be a non-empty string")
        if not isinstance(interval_ticks, int) or interval_ticks <= 0:
            raise ValueError("interval_ticks must be a positive integer")
        if not isinstance(start_tick, int) or start_tick < 0:
            raise ValueError("start_tick must be a non-negative integer")

        existing_interval = self._task_intervals.get(task_name)
        if existing_interval is not None:
            if existing_interval != interval_ticks:
                raise ValueError(
                    f"periodic task {task_name!r} already registered with interval "
                    f"{existing_interval}; got {interval_ticks}"
                )
            existing_start_tick = self._task_start_ticks[task_name]
            if self._sim is None and existing_start_tick != start_tick:
                raise ValueError(
                    f"periodic task {task_name!r} already registered with start_tick "
                    f"{existing_start_tick}; got {start_tick}"
                )
            if self._sim is not None:
                self._schedule_task_if_absent(self._sim, task_name, interval_ticks, start_tick)
            return

        self._task_intervals[task_name] = interval_ticks
        self._task_start_ticks[task_name] = start_tick
        self._registration_order.append(task_name)

        if self._sim is not None:
            self._schedule_task_if_absent(self._sim, task_name, interval_ticks, start_tick)

    def set_task_callback(self, task_name: str, callback: Callable[[Simulation, int], None]) -> None:
        if task_name not in self._task_intervals:
            raise ValueError(f"cannot set callback for unknown periodic task: {task_name}")
        self._callbacks[task_name] = callback

    def on_simulation_start(self, sim: Simulation) -> None:
        self._sim = sim

        # Rehydrate known task intervals from serialized periodic events on load.
        periodic_events: list[tuple[int, str, int]] = []
        for event in sim.pending_events():
            if event.event_type != PERIODIC_EVENT_TYPE:
                continue
            task_name, interval_ticks = self._task_params(event)
            periodic_events.append((event.tick, task_name, interval_ticks))

        for event_tick, task_name, interval_ticks in sorted(periodic_events, key=lambda entry: (entry[0], entry[1])):
            existing = self._task_intervals.get(task_name)
            if existing is not None and existing != interval_ticks:
                raise ValueError(
                    f"periodic task {task_name!r} has conflicting intervals: {existing} vs {interval_ticks}"
                )
            if existing is None:
                self._task_intervals[task_name] = interval_ticks
                self._task_start_ticks[task_name] = int(event_tick)
                self._registration_order.append(task_name)

        for task_name in self._registration_order:
            self._schedule_task_if_absent(
                sim,
                task_name,
                self._task_intervals[task_name],
                self._task_start_ticks[task_name],
            )

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != PERIODIC_EVENT_TYPE:
            return

        task_name, interval_ticks = self._task_params(event)
        self._task_intervals.setdefault(task_name, interval_ticks)
        self._task_start_ticks.setdefault(task_name, event.tick)
        if task_name not in self._registration_order:
            self._registration_order.append(task_name)

        callback = self._callbacks.get(task_name)
        if callback is not None:
            callback(sim, event.tick)

        sim.schedule_event_at(
            tick=event.tick + interval_ticks,
            event_type=PERIODIC_EVENT_TYPE,
            params={"task": task_name, "interval": interval_ticks},
        )

    def _schedule_task_if_absent(
        self,
        sim: Simulation,
        task_name: str,
        interval_ticks: int,
        start_tick: int,
    ) -> None:
        for event in sim.pending_events():
            if event.event_type != PERIODIC_EVENT_TYPE:
                continue
            event_task, event_interval = self._task_params(event)
            if event_task == task_name:
                if event_interval != interval_ticks:
                    raise ValueError(
                        f"periodic task {task_name!r} has conflicting intervals: "
                        f"{interval_ticks} vs {event_interval}"
                    )
                return
        sim.schedule_event_at(
            tick=start_tick,
            event_type=PERIODIC_EVENT_TYPE,
            params={"task": task_name, "interval": interval_ticks},
        )

    def _task_params(self, event: SimEvent) -> tuple[str, int]:
        task_name = str(event.params["task"])
        interval_ticks = int(event.params["interval"])
        if interval_ticks <= 0:
            raise ValueError("periodic_tick interval must be positive")
        return task_name, interval_ticks
