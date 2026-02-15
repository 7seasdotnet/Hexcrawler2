from __future__ import annotations

from typing import Any

from hexcrawler.sim.core import TRAVEL_STEP_EVENT_TYPE, SimEvent, Simulation
from hexcrawler.sim.location import LocationRef
from hexcrawler.sim.periodic import PeriodicScheduler
from hexcrawler.sim.rules import RuleModule

ENCOUNTER_CHECK_EVENT_TYPE = "encounter_check"
ENCOUNTER_ROLL_EVENT_TYPE = "encounter_roll"
ENCOUNTER_RESULT_STUB_EVENT_TYPE = "encounter_result_stub"
ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE = "encounter_resolve_request"
ENCOUNTER_CHECK_INTERVAL = 10
ENCOUNTER_CONTEXT_GLOBAL = "global"
ENCOUNTER_TRIGGER_IDLE = "idle"
ENCOUNTER_TRIGGER_TRAVEL = "travel"
ENCOUNTER_CHANCE_PERCENT = 20
ENCOUNTER_COOLDOWN_TICKS = 30


class EncounterCheckModule(RuleModule):
    """Phase 4B deterministic encounter eligibility gate skeleton.

    Intentionally content-free: this module only emits and accounts for
    deterministic encounter-check events.
    """

    name = "encounter_check"
    _STATE_LAST_CHECK_TICK = "last_check_tick"
    _STATE_CHECKS_EMITTED = "checks_emitted"
    _STATE_ELIGIBLE_COUNT = "eligible_count"
    _STATE_INELIGIBLE_STREAK = "ineligible_streak"
    _STATE_COOLDOWN_UNTIL_TICK = "cooldown_until_tick"
    _TASK_NAME = "encounter_check:global"
    _RNG_STREAM_NAME = "encounter_check"

    def on_simulation_start(self, sim: Simulation) -> None:
        scheduler = sim.get_rule_module(PeriodicScheduler.name)
        if scheduler is None:
            scheduler = PeriodicScheduler()
            sim.register_rule_module(scheduler)
        if not isinstance(scheduler, PeriodicScheduler):
            raise TypeError("periodic_scheduler module must be a PeriodicScheduler")

        state = self._rules_state(sim)
        sim.set_rules_state(self.name, state)

        scheduler.register_task(
            task_name=self._TASK_NAME,
            interval_ticks=ENCOUNTER_CHECK_INTERVAL,
            start_tick=0,
        )
        scheduler.set_task_callback(self._TASK_NAME, self._build_emit_callback())

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type == TRAVEL_STEP_EVENT_TYPE:
            self._on_travel_step(sim, event)
            return
        if event.event_type == ENCOUNTER_ROLL_EVENT_TYPE:
            self._on_encounter_roll(sim, event)
            return
        if event.event_type == ENCOUNTER_RESULT_STUB_EVENT_TYPE:
            self._on_encounter_result_stub(sim, event)
            return
        if event.event_type != ENCOUNTER_CHECK_EVENT_TYPE:
            return

        state = self._rules_state(sim)
        check_tick = int(event.params.get("tick", event.tick))
        trigger = str(event.params.get("trigger", ENCOUNTER_TRIGGER_IDLE))
        location = self._location_for_check(sim=sim, event=event, trigger=trigger)
        rng = sim.rng_stream(self._RNG_STREAM_NAME)

        state[self._STATE_LAST_CHECK_TICK] = check_tick
        state[self._STATE_CHECKS_EMITTED] = int(state[self._STATE_CHECKS_EMITTED]) + 1

        cooldown_until_tick = int(state[self._STATE_COOLDOWN_UNTIL_TICK])
        if check_tick < cooldown_until_tick:
            state[self._STATE_INELIGIBLE_STREAK] = int(state[self._STATE_INELIGIBLE_STREAK]) + 1
            sim.set_rules_state(self.name, state)
            return

        eligible_roll = rng.randrange(0, 100)
        eligible = eligible_roll < ENCOUNTER_CHANCE_PERCENT

        if eligible:
            state[self._STATE_ELIGIBLE_COUNT] = int(state[self._STATE_ELIGIBLE_COUNT]) + 1
            state[self._STATE_INELIGIBLE_STREAK] = 0
            state[self._STATE_COOLDOWN_UNTIL_TICK] = check_tick + ENCOUNTER_COOLDOWN_TICKS
            encounter_roll = rng.randrange(1, 101)
            sim.schedule_event_at(
                tick=event.tick + 1,
                event_type=ENCOUNTER_ROLL_EVENT_TYPE,
                params={
                    "tick": check_tick,
                    "context": ENCOUNTER_CONTEXT_GLOBAL,
                    "roll": encounter_roll,
                    "trigger": trigger,
                    "location": location.to_dict(),
                },
            )
        else:
            state[self._STATE_INELIGIBLE_STREAK] = int(state[self._STATE_INELIGIBLE_STREAK]) + 1

        sim.set_rules_state(self.name, state)

    def _on_encounter_roll(self, sim: Simulation, event: SimEvent) -> None:
        roll = int(event.params.get("roll", 0))
        category = self._category_for_roll(roll)
        sim.schedule_event_at(
            tick=event.tick + 1,
            event_type=ENCOUNTER_RESULT_STUB_EVENT_TYPE,
            params={
                "tick": int(event.params.get("tick", event.tick)),
                "context": event.params.get("context", ENCOUNTER_CONTEXT_GLOBAL),
                "roll": roll,
                "category": category,
                "trigger": str(event.params.get("trigger", ENCOUNTER_TRIGGER_IDLE)),
                "location": dict(event.params["location"]),
            },
        )

    def _on_travel_step(self, sim: Simulation, event: SimEvent) -> None:
        sim.schedule_event_at(
            tick=event.tick + 1,
            event_type=ENCOUNTER_CHECK_EVENT_TYPE,
            params={
                "tick": int(event.params.get("tick", event.tick)),
                "context": ENCOUNTER_CONTEXT_GLOBAL,
                "trigger": ENCOUNTER_TRIGGER_TRAVEL,
                "location": dict(event.params["location_to"]),
            },
        )

    def _on_encounter_result_stub(self, sim: Simulation, event: SimEvent) -> None:
        sim.schedule_event_at(
            tick=event.tick + 1,
            event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
            params={
                "tick": int(event.params.get("tick", event.tick)),
                "context": event.params.get("context", ENCOUNTER_CONTEXT_GLOBAL),
                "trigger": event.params["trigger"],
                "location": dict(event.params["location"]),
                "roll": event.params["roll"],
                "category": event.params["category"],
            },
        )

    @staticmethod
    def _category_for_roll(roll: int) -> str:
        if not 1 <= roll <= 100:
            raise ValueError("encounter_roll must be in the inclusive range [1, 100]")
        if roll <= 40:
            return "hostile"
        if roll <= 75:
            return "neutral"
        return "omen"


    @staticmethod
    def _idle_location(sim: Simulation) -> LocationRef:
        if not sim.state.entities:
            return LocationRef.from_overworld_hex(next(iter(sorted(sim.state.world.hexes))))
        first_entity = sim.state.entities[sorted(sim.state.entities)[0]]
        return LocationRef.from_overworld_hex(first_entity.hex_coord)

    def _location_for_check(self, sim: Simulation, event: SimEvent, trigger: str) -> LocationRef:
        location_payload = event.params.get("location")
        if isinstance(location_payload, dict):
            return LocationRef.from_dict(location_payload)
        if trigger == ENCOUNTER_TRIGGER_TRAVEL:
            location_to = event.params.get("location_to")
            if not isinstance(location_to, dict):
                raise ValueError("travel_step must include location_to")
            return LocationRef.from_dict(location_to)
        return self._idle_location(sim)

    def _build_emit_callback(self):
        def _emit(sim: Simulation, tick: int) -> None:
            sim.schedule_event_at(
                tick=tick + 1,
                event_type=ENCOUNTER_CHECK_EVENT_TYPE,
                params={
                    "tick": tick,
                    "context": ENCOUNTER_CONTEXT_GLOBAL,
                    "trigger": ENCOUNTER_TRIGGER_IDLE,
                    "location": self._idle_location(sim).to_dict(),
                },
            )

        return _emit

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        last_check_tick = int(state.get(self._STATE_LAST_CHECK_TICK, -1))
        checks_emitted = int(state.get(self._STATE_CHECKS_EMITTED, 0))
        eligible_count = int(state.get(self._STATE_ELIGIBLE_COUNT, 0))
        ineligible_streak = int(state.get(self._STATE_INELIGIBLE_STREAK, 0))
        cooldown_until_tick = int(state.get(self._STATE_COOLDOWN_UNTIL_TICK, -1))
        if checks_emitted < 0:
            raise ValueError("checks_emitted must be non-negative")
        if eligible_count < 0:
            raise ValueError("eligible_count must be non-negative")
        if ineligible_streak < 0:
            raise ValueError("ineligible_streak must be non-negative")
        return {
            self._STATE_LAST_CHECK_TICK: last_check_tick,
            self._STATE_CHECKS_EMITTED: checks_emitted,
            self._STATE_ELIGIBLE_COUNT: eligible_count,
            self._STATE_INELIGIBLE_STREAK: ineligible_streak,
            self._STATE_COOLDOWN_UNTIL_TICK: cooldown_until_tick,
        }
