"""Text and JSON report rendering."""

import json

from podcheck.deep import DeepContext, WarningEvent
from podcheck.health import PodHealth, TriageReport


def follow_up_command(namespace: str, name: str) -> str:
    """Return a read-only command useful for inspecting a pod."""
    return f"kubectl describe pod {name} -n {namespace}"


def _pod_payload(pod_health: PodHealth) -> dict[str, object]:
    pod = pod_health.pod
    payload: dict[str, object] = {
        "namespace": pod.namespace,
        "name": pod.name,
        "phase": pod.phase,
        "healthy": pod_health.healthy,
        "containers": [
            {
                "name": container.name,
                "ready": container.ready,
                "restart_count": container.restart_count,
            }
            for container in pod.containers
        ],
        "unready_containers": [
            container.name for container in pod.containers if container.ready is False
        ],
        "reasons": list(pod_health.reasons),
        "follow_up": follow_up_command(pod.namespace, pod.name),
    }
    if pod_health.deep is not None:
        payload["deep"] = _deep_payload(pod_health.deep)
    return payload


def _deep_payload(deep: DeepContext) -> dict[str, object]:
    def event_payload(event: WarningEvent) -> dict[str, object]:
        return {
            "reason": event.reason,
            "message": event.message,
            "timestamp": event.timestamp,
        }

    workload = None
    if deep.workload is not None:
        workload = {
            "kind": deep.workload.kind,
            "name": deep.workload.name,
            "status": deep.workload.status,
        }
    return {
        "owner_chain": [
            {"kind": owner.kind, "name": owner.name}
            for owner in deep.owner_chain
        ],
        "workload": workload,
        "pod_events": [event_payload(event) for event in deep.pod_events],
        "workload_events": [event_payload(event) for event in deep.workload_events],
        "timeline": [
            {
                "source": event.source,
                "reason": event.reason,
                "message": event.message,
                "timestamp": event.timestamp,
            }
            for event in deep.timeline
        ],
        "diagnosis": deep.diagnosis,
        "errors": list(deep.errors),
    }


def render_json(report: TriageReport) -> str:
    """Serialize a triage report as JSON."""
    payload = {
        "scope": report.scope,
        "pods": [_pod_payload(pod) for pod in report.pods],
    }
    return json.dumps(payload, indent=2)


def render_text(report: TriageReport) -> str:
    """Render pod health, container details, and safe follow-up commands."""
    lines = [f"Pod health report ({report.scope})"]
    if not report.pods:
        lines.append("No pods found.")
    for result in report.pods:
        pod = result.pod
        state = "HEALTHY" if result.healthy else "UNHEALTHY"
        phase = pod.phase if pod.phase is not None else "unknown"
        lines.append(f"{state} {pod.namespace}/{pod.name} (phase: {phase})")
        for container in pod.containers:
            ready = "unknown" if container.ready is None else str(container.ready).lower()
            restarts = (
                "unknown"
                if container.restart_count is None
                else str(container.restart_count)
            )
            lines.append(
                f"  Container {container.name}: ready={ready}, restarts={restarts}"
            )
        for reason in result.reasons:
            lines.append(f"  Reason: {reason}")
        if result.deep is not None:
            deep = result.deep
            owner_text = " -> ".join(
                f"{owner.kind}/{owner.name}" for owner in deep.owner_chain
            ) or "none"
            lines.append(f"  Owner chain: {owner_text}")
            if deep.workload is not None:
                lines.append(
                    f"  Workload status ({deep.workload.kind}/"
                    f"{deep.workload.name}): {deep.workload.status}"
                )
            for event in deep.timeline:
                when = event.timestamp if event.timestamp is not None else "unknown time"
                summary = ": ".join(
                    part for part in (event.reason, event.message) if part
                ) or "Warning event"
                lines.append(f"  Timeline [{when}] {event.source}: {summary}")
            lines.append(f"  Diagnosis: {deep.diagnosis}")
            for error in deep.errors:
                lines.append(f"  Deep lookup warning: {error}")
        lines.append(f"  Follow-up: {follow_up_command(pod.namespace, pod.name)}")
    return "\n".join(lines)
