"""Pod data structures and health classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from podcheck.deep import DeepContext


@dataclass(frozen=True)
class OwnerReference:
    kind: str
    name: str
    controller: bool | None = None


@dataclass(frozen=True)
class ContainerInfo:
    name: str
    ready: bool | None
    restart_count: int | None


@dataclass(frozen=True)
class PodInfo:
    namespace: str
    name: str
    phase: str | None
    containers: tuple[ContainerInfo, ...]
    owners: tuple[OwnerReference, ...] = ()


@dataclass(frozen=True)
class PodHealth:
    pod: PodInfo
    reasons: tuple[str, ...]
    deep: DeepContext | None = None

    @property
    def healthy(self) -> bool:
        return not self.reasons


@dataclass(frozen=True)
class TriageReport:
    scope: str
    pods: tuple[PodHealth, ...]


def inspect_pod(pod: PodInfo) -> PodHealth:
    """Classify a normalized pod and explain any unhealthy state."""
    reasons: list[str] = []
    if pod.phase != "Running":
        phase = pod.phase if pod.phase is not None else "unknown"
        reasons.append(f"phase is {phase}")
    for container in pod.containers:
        if container.ready is False:
            reasons.append(f"container {container.name} is not ready")
    return PodHealth(pod=pod, reasons=tuple(reasons))


def inspect_pods(
    pods: list[PodInfo], scope: str, failing_only: bool = False
) -> TriageReport:
    """Build a report for pods, optionally omitting healthy pods."""
    inspected = tuple(inspect_pod(pod) for pod in pods)
    if failing_only:
        inspected = tuple(pod for pod in inspected if not pod.healthy)
    return TriageReport(scope=scope, pods=inspected)
