from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum

from .models import ConnectionTarget, ScanResult


class TransportType(StrEnum):
    SERIAL = "serial"
    SSH = "ssh"


class TransportError(RuntimeError):
    """Base transport exception."""


class Transport(ABC):
    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def write(self, data: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def read_available(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def read_until(self, markers: Sequence[str], timeout: float) -> tuple[str | None, str]:
        raise NotImplementedError

    @abstractmethod
    def send_command(self, command: str, wait: float = 1.0) -> str:
        raise NotImplementedError

    @abstractmethod
    def interrupt(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_connected(self) -> bool:
        raise NotImplementedError


class TransportFactory(ABC):
    transport_type: TransportType

    @abstractmethod
    def list_targets(self) -> list[ConnectionTarget]:
        raise NotImplementedError

    @abstractmethod
    def probe(self, target: ConnectionTarget, markers: Sequence[str], timeout: float) -> ScanResult:
        raise NotImplementedError

    @abstractmethod
    def create(self, target: ConnectionTarget) -> Transport:
        raise NotImplementedError
