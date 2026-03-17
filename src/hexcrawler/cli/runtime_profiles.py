from __future__ import annotations

from typing import Final, Literal

from hexcrawler.content.encounters import DEFAULT_ENCOUNTER_TABLE_PATH, load_encounter_table_json
from hexcrawler.sim.campaign_danger import CampaignDangerModule
from hexcrawler.sim.combat import CombatExecutionModule
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.encounters import (
    EncounterActionExecutionModule,
    EncounterActionModule,
    EncounterCheckModule,
    EncounterSelectionModule,
    LocalEncounterInstanceModule,
    LocalEncounterRequestModule,
    RumorDecayModule,
    RumorPipelineModule,
    RumorQueryModule,
    SiteEcologyModule,
    SpawnMaterializationModule,
)
from hexcrawler.sim.entity_stats import EntityStatsExecutionModule
from hexcrawler.sim.exploration import ExplorationExecutionModule
from hexcrawler.sim.groups import GroupMovementModule
from hexcrawler.sim.interactions import InteractionExecutionModule
from hexcrawler.sim.local_hostiles import LocalHostileBehaviorModule
from hexcrawler.sim.signals import SignalPropagationModule
from hexcrawler.sim.supplies import SupplyConsumptionModule

RuntimeProfile = Literal["core_playable", "experimental_world", "soak_audit"]

CORE_PLAYABLE: Final[RuntimeProfile] = "core_playable"
EXPERIMENTAL_WORLD: Final[RuntimeProfile] = "experimental_world"
SOAK_AUDIT: Final[RuntimeProfile] = "soak_audit"
DEFAULT_RUNTIME_PROFILE: Final[RuntimeProfile] = CORE_PLAYABLE
RUNTIME_PROFILE_CHOICES: Final[tuple[RuntimeProfile, ...]] = (
    CORE_PLAYABLE,
    EXPERIMENTAL_WORLD,
    SOAK_AUDIT,
)

_CORE_PLAYABLE_MODULE_NAMES: Final[tuple[str, ...]] = (
    EncounterCheckModule.name,
    EncounterSelectionModule.name,
    EncounterActionModule.name,
    EncounterActionExecutionModule.name,
    LocalEncounterRequestModule.name,
    LocalEncounterInstanceModule.name,
    LocalHostileBehaviorModule.name,
    CampaignDangerModule.name,
    SpawnMaterializationModule.name,
    GroupMovementModule.name,
    ExplorationExecutionModule.name,
    EntityStatsExecutionModule.name,
    CombatExecutionModule.name,
    SupplyConsumptionModule.name,
)

_EXPERIMENTAL_EXTRA_MODULE_NAMES: Final[tuple[str, ...]] = (
    InteractionExecutionModule.name,
    SignalPropagationModule.name,
    SiteEcologyModule.name,
    RumorPipelineModule.name,
    RumorDecayModule.name,
    RumorQueryModule.name,
)

_SOAK_AUDIT_EXTRA_MODULE_NAMES: Final[tuple[str, ...]] = (
    SignalPropagationModule.name,
    RumorQueryModule.name,
)


def _register(sim: Simulation, module: object) -> None:
    name = getattr(module, "name", None)
    if not isinstance(name, str) or not name:
        raise TypeError("rule module must expose non-empty name")
    if sim.get_rule_module(name) is not None:
        return
    sim.register_rule_module(module)


def _register_core_playable_modules(sim: Simulation) -> None:
    _register(sim, EncounterCheckModule())
    _register(sim, EncounterSelectionModule(load_encounter_table_json(DEFAULT_ENCOUNTER_TABLE_PATH)))
    _register(sim, EncounterActionModule())
    _register(sim, EncounterActionExecutionModule())
    _register(sim, LocalEncounterRequestModule())
    _register(sim, LocalEncounterInstanceModule())
    _register(sim, LocalHostileBehaviorModule())
    _register(sim, CampaignDangerModule())
    _register(sim, SpawnMaterializationModule())
    _register(sim, GroupMovementModule())
    _register(sim, ExplorationExecutionModule())
    _register(sim, EntityStatsExecutionModule())
    _register(sim, CombatExecutionModule())
    _register(sim, SupplyConsumptionModule())


def _register_experimental_world_modules(sim: Simulation) -> None:
    _register_core_playable_modules(sim)
    _register(sim, InteractionExecutionModule())
    _register(sim, SignalPropagationModule())
    _register(sim, SiteEcologyModule())
    _register(sim, RumorPipelineModule())
    _register(sim, RumorDecayModule())
    _register(sim, RumorQueryModule())


def _register_soak_audit_modules(sim: Simulation) -> None:
    _register_core_playable_modules(sim)
    _register(sim, SignalPropagationModule())
    _register(sim, RumorQueryModule())


def configure_runtime_profile(sim: Simulation, profile: RuntimeProfile) -> None:
    if profile == CORE_PLAYABLE:
        _register_core_playable_modules(sim)
        return
    if profile == EXPERIMENTAL_WORLD:
        _register_experimental_world_modules(sim)
        return
    if profile == SOAK_AUDIT:
        _register_soak_audit_modules(sim)
        return
    raise ValueError(f"unsupported runtime profile: {profile}")


def module_names_for_profile(profile: RuntimeProfile) -> tuple[str, ...]:
    by_profile: dict[RuntimeProfile, tuple[str, ...]] = {
        CORE_PLAYABLE: _CORE_PLAYABLE_MODULE_NAMES,
        EXPERIMENTAL_WORLD: _CORE_PLAYABLE_MODULE_NAMES + _EXPERIMENTAL_EXTRA_MODULE_NAMES,
        SOAK_AUDIT: _CORE_PLAYABLE_MODULE_NAMES + _SOAK_AUDIT_EXTRA_MODULE_NAMES,
    }
    return by_profile[profile]


def configure_non_encounter_viewer_modules(sim: Simulation) -> None:
    _register(sim, ExplorationExecutionModule())
    _register(sim, InteractionExecutionModule())
    _register(sim, SignalPropagationModule())
    _register(sim, EntityStatsExecutionModule())
    _register(sim, CombatExecutionModule())
    _register(sim, SupplyConsumptionModule())
