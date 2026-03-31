from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import default_project_root
from ..core.models import ConnectionTarget, ScanResult
from .factory import ReplayReadUntilResult, ReplayTransportPlan

VALID_ACTIONS = {"scan", "stage1", "stage2", "stage3", "full"}


@dataclass(slots=True)
class ReplayScenario:
    name: str
    display_name: str
    action: str
    description: str
    supported_actions: tuple[str, ...]
    target: ConnectionTarget
    probe_result: ScanResult
    transport_plans: list[ReplayTransportPlan]
    firmware_name: str = ""
    stage1_complete: bool = False
    stage2_complete: bool = False
    artifact_mutations: dict[str, Any] | None = None


def default_scenario_dir() -> Path:
    return default_project_root() / "replay_scenarios"


def resolve_scenario_path(value: str | Path, scenario_dir: Path | None = None) -> Path:
    scenario_root = scenario_dir or default_scenario_dir()
    path = Path(value)
    if path.exists():
        return path
    if path.suffix != ".toml":
        candidate = scenario_root / f"{path.name}.toml"
        if candidate.exists():
            return candidate
    candidate = scenario_root / path.name
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Replay scenario not found: {value}")


def _as_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Expected a list of strings in replay fixture")
    return list(value)


def _as_outputs(mapping: object) -> dict[str, list[str]]:
    if mapping is None:
        return {}
    if not isinstance(mapping, dict):
        raise ValueError("Expected [transports.commands] table in replay fixture")
    outputs: dict[str, list[str]] = {}
    for key, value in mapping.items():
        if not isinstance(key, str):
            raise ValueError("Command output keys must be strings")
        if isinstance(value, str):
            outputs[key] = [value]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            outputs[key] = list(value)
        else:
            raise ValueError(f"Unsupported command output payload for {key!r}")
    return outputs


def _default_supported_actions(action: str) -> tuple[str, ...]:
    if action == "scan":
        return ("scan",)
    if action == "stage1":
        return ("scan", "stage1")
    if action == "stage2":
        return ("scan", "stage2")
    if action == "stage3":
        return ("scan", "stage3")
    if action == "full":
        return ("scan", "stage1", "stage2", "stage3")
    return ("scan",)


def _normalize_supported_actions(value: object, action: str) -> tuple[str, ...]:
    items = _as_string_list(value)
    if not items:
        return _default_supported_actions(action)
    allowed = VALID_ACTIONS - {"full"}
    normalized: list[str] = []
    for item in items:
        action_name = item.strip().lower()
        if action_name not in allowed:
            raise ValueError(f"Unsupported supported_actions value: {item}")
        if action_name not in normalized:
            normalized.append(action_name)
    return tuple(normalized)


def _normalize_artifact_mutations(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Expected [artifact_mutations] table in replay fixture")
    normalized: dict[str, Any] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            raise ValueError("artifact_mutations keys must be strings")
        if isinstance(raw, (str, bool)):
            normalized[key] = raw
            continue
        if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
            normalized[key] = list(raw)
            continue
        if isinstance(raw, dict):
            converted: dict[str, str] = {}
            for nested_key, nested_value in raw.items():
                if not isinstance(nested_key, str) or not isinstance(nested_value, str):
                    raise ValueError("artifact_mutations nested tables must be string-to-string")
                converted[nested_key] = nested_value
            normalized[key] = converted
            continue
        raise ValueError(f"Unsupported artifact_mutations payload for {key!r}")
    return normalized or None


def load_scenario(value: str | Path, scenario_dir: Path | None = None) -> ReplayScenario:
    path = resolve_scenario_path(value, scenario_dir=scenario_dir)
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    action = str(data.get("action", "scan")).strip().lower()
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unsupported replay action: {action}")

    target_data = data.get("target", {})
    if not isinstance(target_data, dict):
        raise ValueError("Replay fixture must contain [target]")
    target = ConnectionTarget(
        id=str(target_data.get("id", "")).strip(),
        label=str(target_data.get("label", "")).strip() or str(target_data.get("id", "")).strip(),
        metadata=dict(target_data.get("metadata", {})),
    )
    if not target.id:
        raise ValueError("Replay fixture target.id is required")

    probe_data = data.get("probe", {})
    if not isinstance(probe_data, dict):
        raise ValueError("Replay fixture must contain [probe]")
    prompt_type = str(probe_data.get("prompt_type", "")).strip()
    probe_result = ScanResult(
        target=target,
        available=bool(probe_data.get("available", True)),
        status_message=str(probe_data.get("status_message", "")).strip() or "Replay probe result",
        prompt_type=prompt_type or None,
        version=str(probe_data.get("version", "")),
        connection_state=str(probe_data.get("connection_state", "unknown")),
        recommended_next_action=str(probe_data.get("recommended_next_action", "")),
        error_code=str(probe_data.get("error_code", "")),
        score=int(probe_data.get("score", 0)),
        raw_preview=str(probe_data.get("raw_preview", "")),
    )

    transport_plans: list[ReplayTransportPlan] = []
    for index, item in enumerate(data.get("transports", []), start=1):
        if not isinstance(item, dict):
            raise ValueError("Replay fixture [[transports]] entries must be tables")
        read_until_results = [
            ReplayReadUntilResult(
                marker=(str(step.get("marker", "")).strip() or None),
                buffer=str(step.get("buffer", "")),
            )
            for step in item.get("read_until", [])
        ]
        transport_plans.append(
            ReplayTransportPlan(
                name=str(item.get("name", f"transport-{index}")),
                command_outputs=_as_outputs(item.get("commands")),
                read_until_results=read_until_results,
                read_available_chunks=_as_string_list(item.get("read_available_chunks")),
                default_output=str(item.get("default_output", "")),
                disconnect_after_commands=set(
                    _as_string_list(item.get("disconnect_after_commands"))
                ),
            )
        )

    return ReplayScenario(
        name=str(data.get("name", path.stem)),
        display_name=str(data.get("display_name", data.get("name", path.stem))),
        action=action,
        description=str(data.get("description", "")),
        supported_actions=_normalize_supported_actions(data.get("supported_actions"), action),
        target=target,
        probe_result=probe_result,
        transport_plans=transport_plans,
        firmware_name=str(data.get("firmware_name", "")),
        stage1_complete=bool(data.get("stage1_complete", False)),
        stage2_complete=bool(data.get("stage2_complete", False)),
        artifact_mutations=_normalize_artifact_mutations(data.get("artifact_mutations")),
    )


def load_scenarios(directory: Path | None = None) -> list[ReplayScenario]:
    directory = directory or default_scenario_dir()
    return [load_scenario(path) for path in sorted(directory.glob("*.toml"))]
