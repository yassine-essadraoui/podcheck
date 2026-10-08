"""Optional workload and event enrichment for failing pods."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from kubernetes.client.exceptions import ApiException

from podcheck.health import OwnerReference, PodHealth, TriageReport

if TYPE_CHECKING:
    from podcheck.kubernetes import PodReader

SUPPORTED_WORKLOADS = {"ReplicaSet", "Deployment", "StatefulSet", "DaemonSet", "Job"}


@dataclass(frozen=True)
class WorkloadInfo:
    kind: str
    name: str
    owners: tuple[OwnerReference, ...]
    status: dict[str, object]


@dataclass(frozen=True)
class WarningEvent:
    reason: str | None
    message: str | None
    timestamp: str | None


@dataclass(frozen=True)
class TimelineEvent:
    source: str
    reason: str | None
    message: str | None
    timestamp: str | None


@dataclass(frozen=True)
class DeepContext:
    owner_chain: tuple[OwnerReference, ...]
    workload: WorkloadInfo | None
    pod_events: tuple[WarningEvent, ...]
    workload_events: tuple[WarningEvent, ...]
    timeline: tuple[TimelineEvent, ...]
    diagnosis: str
    errors: tuple[str, ...]


def enrich_report(reader: PodReader, report: TriageReport) -> TriageReport:
    """Enrich failing pods, preserving the original report on lookup failures."""
    enriched = tuple(
        replace(item, deep=enrich_pod(reader, item)) if not item.healthy else item
        for item in report.pods
    )
    return replace(report, pods=enriched)


def enrich_pod(reader: PodReader, result: PodHealth) -> DeepContext:
    """Resolve owner/workload context and recent Warning events for one pod."""
    pod = result.pod
    owner_chain: list[OwnerReference] = []
    errors: list[str] = []
    workload: WorkloadInfo | None = None
    candidates = _ordered_owners(pod.owners)

    while candidates:
        owner = candidates.pop(0)
        if owner.kind not in SUPPORTED_WORKLOADS:
            owner_chain.append(owner)
            break
        if any(item.kind == owner.kind and item.name == owner.name for item in owner_chain):
            errors.append("Workload owner chain contains a cycle.")
            break
        owner_chain.append(owner)
        try:
            workload = reader.read_workload(owner.kind, pod.namespace, owner.name)
        except ApiException as error:
            errors.append(f"Could not read {owner.kind} {owner.name}: {error}")
            workload = None
            break
        if workload is None:
            errors.append(f"Owning {owner.kind} {owner.name} was not found.")
            break
        if owner.kind == "ReplicaSet":
            candidates = _ordered_owners(workload.owners)
            if not candidates:
                break
            continue
        break

    try:
        pod_events = tuple(reader.list_warning_events(pod.namespace, "Pod", pod.name))
    except ApiException as error:
        pod_events = ()
        errors.append(f"Could not read Warning events for Pod {pod.name}: {error}")

    workload_events: tuple[WarningEvent, ...] = ()
    if workload is not None:
        try:
            workload_events = tuple(
                reader.list_warning_events(pod.namespace, workload.kind, workload.name)
            )
        except ApiException as error:
            errors.append(
                f"Could not read Warning events for {workload.kind} "
                f"{workload.name}: {error}"
            )

    timeline = _build_timeline(pod_events, workload_events)
    diagnosis = _diagnose(result, workload, timeline)
    return DeepContext(
        owner_chain=tuple(owner_chain),
        workload=workload,
        pod_events=pod_events,
        workload_events=workload_events,
        timeline=timeline,
        diagnosis=diagnosis,
        errors=tuple(errors),
    )


def _ordered_owners(owners: tuple[OwnerReference, ...]) -> list[OwnerReference]:
    """Prefer the controller owner, falling back to the first owner."""
    if not owners:
        return []
    controller = next((owner for owner in owners if owner.controller), None)
    return [controller or owners[0]]


def _build_timeline(
    pod_events: tuple[WarningEvent, ...], workload_events: tuple[WarningEvent, ...]
) -> tuple[TimelineEvent, ...]:
    timeline = [
        TimelineEvent("pod", event.reason, event.message, event.timestamp)
        for event in pod_events
    ]
    timeline.extend(
        TimelineEvent("workload", event.reason, event.message, event.timestamp)
        for event in workload_events
    )
    return tuple(sorted(timeline, key=lambda event: _timestamp_key(event.timestamp)))


def _timestamp_key(timestamp: str | None) -> datetime:
    if timestamp is None:
        return datetime.max.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return datetime.max.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _diagnose(
    result: PodHealth,
    workload: WorkloadInfo | None,
    timeline: tuple[TimelineEvent, ...],
) -> str:
    evidence: list[str] = []
    if workload is not None and workload.kind == "Deployment":
        unavailable = workload.status.get("unavailable_replicas")
        if isinstance(unavailable, int) and unavailable > 0:
            evidence.append(f"Deployment has {unavailable} unavailable replicas.")
        conditions = workload.status.get("conditions", [])
        if isinstance(conditions, list):
            for condition in conditions:
                if not isinstance(condition, dict):
                    continue
                if condition.get("type") == "Progressing" and condition.get("status") == "False":
                    reason = condition.get("reason")
                    message = condition.get("message")
                    detail = ": ".join(
                        str(value) for value in (reason, message) if value
                    )
                    evidence.append(
                        f"Deployment Progressing condition is False"
                        f"{f' ({detail})' if detail else ''}."
                    )
    event_details = [
        ": ".join(part for part in (event.reason, event.message) if part)
        for event in timeline
        if event.reason or event.message
    ]
    if event_details:
        evidence.append("Warning events: " + "; ".join(event_details) + ".")
    if evidence:
        return " ".join(evidence)
    return "Pod is unhealthy: " + "; ".join(result.reasons)
