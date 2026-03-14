from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..core.logging_utils import append_transcript_line
from ..core.models import ConnectionTarget, ScanResult
from ..core.transport import Transport, TransportFactory, TransportType


@dataclass(slots=True)
class ReplayReadUntilResult:
    marker: str | None
    buffer: str


@dataclass(slots=True)
class ReplayTransportPlan:
    name: str
    command_outputs: dict[str, list[str]] = field(default_factory=dict)
    read_until_results: list[ReplayReadUntilResult] = field(default_factory=list)
    read_available_chunks: list[str] = field(default_factory=list)
    default_output: str = ""
    disconnect_after_commands: set[str] = field(default_factory=set)

    def build(self, transcript_path: Path) -> ReplayTransport:
        return ReplayTransport(
            transcript_path=transcript_path,
            command_outputs={key: list(value) for key, value in self.command_outputs.items()},
            read_until_results=list(self.read_until_results),
            read_available_chunks=list(self.read_available_chunks),
            default_output=self.default_output,
            disconnect_after_commands=set(self.disconnect_after_commands),
        )


class ReplayTransport(Transport):
    def __init__(
        self,
        *,
        transcript_path: Path,
        command_outputs: dict[str, list[str]],
        read_until_results: list[ReplayReadUntilResult],
        read_available_chunks: list[str],
        default_output: str,
        disconnect_after_commands: set[str],
    ) -> None:
        self.transcript_path = transcript_path
        self.command_outputs = command_outputs
        self.read_until_results = read_until_results
        self.read_available_chunks = read_available_chunks
        self.default_output = default_output
        self.disconnect_after_commands = disconnect_after_commands
        self.connected = False
        self.interrupted = False
        self.writes: list[str] = []

    def _transcript(self, direction: str, payload: str) -> None:
        if payload:
            append_transcript_line(self.transcript_path, direction, payload)

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def write(self, data: str) -> None:
        self.writes.append(data)
        self._transcript("WRITE", data if data else "<ENTER>")

    def read_available(self) -> str:
        if not self.read_available_chunks:
            return ""
        chunk = self.read_available_chunks.pop(0)
        self._transcript("READ", chunk)
        return chunk

    def read_until(self, markers: Sequence[str], timeout: float) -> tuple[str | None, str]:
        del timeout
        if not self.read_until_results:
            return None, ""
        result = self.read_until_results.pop(0)
        if result.marker is not None and result.marker not in markers:
            expected = ", ".join(markers)
            raise RuntimeError(
                "Replay fixture returned marker "
                f"{result.marker!r}, but workflow expected one of: {expected}"
            )
        self._transcript("READ", result.buffer)
        return result.marker, result.buffer

    def send_command(self, command: str, wait: float = 1.0) -> str:
        del wait
        self.writes.append(command)
        self._transcript("WRITE", command)
        if command in self.command_outputs and self.command_outputs[command]:
            output = self.command_outputs[command].pop(0)
        else:
            output = ""
            for key, values in self.command_outputs.items():
                if key.endswith("*") and command.startswith(key[:-1]) and values:
                    output = values.pop(0)
                    break
            if not output:
                output = self.default_output
        self._transcript("READ", output)
        if command in self.disconnect_after_commands:
            self.connected = False
        return output

    def interrupt(self) -> None:
        self.interrupted = True

    def is_connected(self) -> bool:
        return self.connected

    def reset_interrupt(self) -> None:
        self.interrupted = False


class ReplayTransportFactory(TransportFactory):
    transport_type = TransportType.SERIAL

    def __init__(
        self,
        *,
        target: ConnectionTarget,
        probe_result: ScanResult,
        transport_plans: list[ReplayTransportPlan],
        transcript_path: Path,
    ) -> None:
        self.target = target
        self.probe_result = probe_result
        self.transport_plans = list(transport_plans)
        self.transcript_path = transcript_path

    def list_targets(self) -> list[ConnectionTarget]:
        return [self.target]

    def probe(self, target: ConnectionTarget, markers: Sequence[str], timeout: float) -> ScanResult:
        del markers, timeout
        if target.id != self.target.id:
            raise RuntimeError(f"Replay target {target.id!r} is not defined in the loaded scenario")
        return self.probe_result

    def create(self, target: ConnectionTarget) -> Transport:
        if target.id != self.target.id:
            raise RuntimeError(f"Replay target {target.id!r} is not defined in the loaded scenario")
        if not self.transport_plans:
            raise RuntimeError("Replay fixture has no transport plan left for create()")
        return self.transport_plans.pop(0).build(self.transcript_path)
