from __future__ import annotations

import argparse
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ..config import AppConfig, SessionPaths, WorkflowTiming
from ..core.events import AppEvent
from ..core.models import DeviceSnapshot, OperatorMessage
from ..core.workflow import WorkflowController
from ..profiles import build_c2960x_profile
from .factory import ReplayTransportFactory
from .loader import ReplayScenario, load_scenario


@dataclass(slots=True)
class ReplayRunResult:
    scenario_name: str
    action: str
    final_state: str
    selected_target_id: str
    stage1_complete: bool
    stage2_complete: bool
    event_counts: dict[str, int]
    events: list[AppEvent]
    log_path: Path
    transcript_path: Path
    report_path: Path
    device_snapshot: DeviceSnapshot
    operator_message: OperatorMessage

    def to_lines(self) -> list[str]:
        return [
            f"Scenario: {self.scenario_name}",
            f"Action: {self.action}",
            f"Final state: {self.final_state}",
            f"Selected target: {self.selected_target_id or '—'}",
            f"Stage 1 complete: {self.stage1_complete}",
            f"Stage 2 complete: {self.stage2_complete}",
            f"Operator: {self.operator_message.severity} | {self.operator_message.title}",
            f"Next step: {self.operator_message.next_step or '—'}",
            f"Session log: {self.log_path}",
            f"Transcript: {self.transcript_path}",
            f"Report: {self.report_path}",
            f"Event counts: {self.event_counts}",
        ]


class ReplayRunner:
    def __init__(
        self,
        scenario: ReplayScenario,
        *,
        runtime_root: Path | None = None,
        timing: WorkflowTiming | None = None,
    ) -> None:
        self.scenario = scenario
        self.runtime_root = runtime_root
        self.timing = timing or WorkflowTiming(
            command_wait_short=0.0,
            command_wait_medium=0.0,
            command_wait_long=0.0,
            prompt_timeout=0.1,
            enable_timeout=0.1,
            reload_confirm_timeout=0.1,
            stage1_prompt_timeout=0.2,
            install_timeout=0.2,
            install_quiet_success=0.0,
            stage2_prompt_timeout=0.1,
            scan_probe_timeout=0.1,
            heartbeat_interval=0.01,
        )

    @staticmethod
    def _rewrite_report_fields(report_path: Path, overrides: dict[str, str]) -> None:
        lines = report_path.read_text(encoding="utf-8").splitlines()
        updated: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if ":" not in line:
                updated.append(line)
                continue
            key, _value = line.split(":", 1)
            key = key.strip()
            if key in overrides:
                updated.append(f"{key}: {overrides[key]}")
                seen.add(key)
            else:
                updated.append(line)
        for key, value in overrides.items():
            if key not in seen:
                updated.append(f"{key}: {value}")
        report_path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")

    def _apply_artifact_mutations(self, session: SessionPaths) -> None:
        mutations = self.scenario.artifact_mutations or {}
        if not mutations:
            return
        if bool(mutations.get("delete_report")) and session.report_path.exists():
            session.report_path.unlink()
        if bool(mutations.get("empty_transcript")) and session.transcript_path.exists():
            session.transcript_path.write_text("", encoding="utf-8")
        report_field_overrides = mutations.get("report_field_overrides")
        if (
            isinstance(report_field_overrides, dict)
            and report_field_overrides
            and session.report_path.exists()
        ):
            self._rewrite_report_fields(session.report_path, report_field_overrides)

    def _create_session(self) -> tuple[Path | None, SessionPaths]:
        if self.runtime_root is None:
            temp_root = Path(tempfile.mkdtemp(prefix="ciscoautoflash-replay-"))
            config = AppConfig(runtime_root=temp_root)
            return temp_root, config.create_session_paths()
        config = AppConfig(runtime_root=self.runtime_root)
        return None, config.create_session_paths()

    def run(
        self,
        *,
        action: str | None = None,
        firmware_name: str | None = None,
    ) -> ReplayRunResult:
        selected_action = (action or self.scenario.action).lower()
        if selected_action not in {"scan", "stage1", "stage2", "stage3", "full"}:
            raise ValueError(f"Unsupported replay action: {selected_action}")

        _temp_root, session = self._create_session()
        events: list[AppEvent] = []
        factory = ReplayTransportFactory(
            target=self.scenario.target,
            probe_result=self.scenario.probe_result,
            transport_plans=list(self.scenario.transport_plans),
            transcript_path=session.transcript_path,
        )
        controller = WorkflowController(
            profile=build_c2960x_profile(),
            transport_factory=factory,
            session=session,
            event_handler=events.append,
            timing=self.timing,
        )
        controller.initialize()
        controller.scan_devices(background=False)
        controller.stage1_complete = self.scenario.stage1_complete
        controller.stage2_complete = self.scenario.stage2_complete

        effective_firmware = (
            firmware_name or self.scenario.firmware_name or controller.profile.default_firmware
        )

        if selected_action == "stage1":
            controller.run_stage1(background=False)
        elif selected_action == "stage2":
            controller.run_stage2(effective_firmware, background=False)
        elif selected_action == "stage3":
            controller.run_stage3(background=False)
        elif selected_action == "full":
            controller.run_stage1(background=False)
            controller.run_stage2(effective_firmware, background=False)
            controller.run_stage3(background=False)

        self._apply_artifact_mutations(session)

        return ReplayRunResult(
            scenario_name=self.scenario.name,
            action=selected_action,
            final_state=controller.state.value,
            selected_target_id=controller.selected_target.id if controller.selected_target else "",
            stage1_complete=controller.stage1_complete,
            stage2_complete=controller.stage2_complete,
            event_counts=dict(Counter(event.kind for event in events)),
            events=events,
            log_path=session.log_path,
            transcript_path=session.transcript_path,
            report_path=session.report_path,
            device_snapshot=controller.device_snapshot,
            operator_message=controller.operator_message,
        )


def run_scenario(
    scenario_path: str | Path,
    *,
    action: str | None = None,
    firmware_name: str | None = None,
    runtime_root: Path | None = None,
) -> ReplayRunResult:
    scenario = load_scenario(scenario_path)
    return ReplayRunner(scenario, runtime_root=runtime_root).run(
        action=action,
        firmware_name=firmware_name,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run canned CiscoAutoFlash replay scenarios.")
    parser.add_argument("scenario", help="Scenario name or path to a .toml fixture")
    parser.add_argument(
        "--action",
        choices=["scan", "stage1", "stage2", "stage3", "full"],
        help="Override the default action from the fixture",
    )
    parser.add_argument("--firmware", help="Override the firmware name for stage 2/full")
    parser.add_argument(
        "--runtime-root",
        type=Path,
        help="Optional runtime root for logs/transcripts/reports",
    )
    parser.add_argument(
        "--show-events",
        action="store_true",
        help="Print emitted AppEvent kinds and payload keys after the summary",
    )
    args = parser.parse_args(argv)

    result = run_scenario(
        args.scenario,
        action=args.action,
        firmware_name=args.firmware,
        runtime_root=args.runtime_root,
    )
    for line in result.to_lines():
        print(line)
    if args.show_events:
        print("Events:")
        for event in result.events:
            keys = ", ".join(sorted(event.payload))
            print(f"- {event.kind}: {keys}")
    return 0
