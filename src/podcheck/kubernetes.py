"""Read-only Kubernetes pod adapter and API-object conversion."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from kubernetes import client, config
from kubernetes.client import V1Pod

from podcheck.deep import WarningEvent, WorkloadInfo
from podcheck.health import ContainerInfo, OwnerReference, PodInfo


class PodReader(Protocol):
    """Interface for retrieving normalized pod data."""

    def list_pods(self, namespace: str | None = None) -> list[PodInfo]: ...

    def read_workload(
        self, kind: str, namespace: str, name: str
    ) -> WorkloadInfo | None: ...

    def list_warning_events(
        self, namespace: str, object_kind: str, object_name: str, limit: int = 10
    ) -> list[WarningEvent]: ...


def pod_from_api(pod: V1Pod) -> PodInfo:
    """Convert an official Kubernetes pod object to internal data."""
    metadata = pod.metadata
    status = pod.status
    namespace = metadata.namespace if metadata and metadata.namespace else "unknown"
    name = metadata.name if metadata and metadata.name else "unknown"
    container_statuses = status.container_statuses if status else None
    containers = tuple(
        ContainerInfo(
            name=item.name or "unknown",
            ready=item.ready,
            restart_count=item.restart_count,
        )
        for item in (container_statuses or [])
    )
    owner_references = metadata.owner_references if metadata else None
    owners = tuple(
        OwnerReference(
            kind=owner.kind or "unknown",
            name=owner.name or "unknown",
            controller=owner.controller,
        )
        for owner in (owner_references or [])
    )
    return PodInfo(
        namespace=namespace,
        name=name,
        phase=status.phase if status else None,
        containers=containers,
        owners=owners,
    )


class KubernetesPodReader:
    """PodReader implementation backed by the official Kubernetes client."""

    def __init__(
        self,
        api: client.CoreV1Api,
        apps_api: client.AppsV1Api | None = None,
        batch_api: client.BatchV1Api | None = None,
    ) -> None:
        self._api = api
        self._apps_api = apps_api or client.AppsV1Api()
        self._batch_api = batch_api or client.BatchV1Api()

    def list_pods(self, namespace: str | None = None) -> list[PodInfo]:
        if namespace is None:
            response = self._api.list_pod_for_all_namespaces()
        else:
            response = self._api.list_namespaced_pod(namespace=namespace)
        return [pod_from_api(pod) for pod in (response.items or [])]

    def read_workload(
        self, kind: str, namespace: str, name: str
    ) -> WorkloadInfo | None:
        """Read and normalize a supported workload object."""
        readers = {
            "ReplicaSet": (self._apps_api, "read_namespaced_replica_set"),
            "Deployment": (self._apps_api, "read_namespaced_deployment"),
            "StatefulSet": (self._apps_api, "read_namespaced_stateful_set"),
            "DaemonSet": (self._apps_api, "read_namespaced_daemon_set"),
            "Job": (self._batch_api, "read_namespaced_job"),
        }
        target = readers.get(kind)
        if target is None:
            return None
        api, method_name = target
        workload = getattr(api, method_name)(name=name, namespace=namespace)
        metadata = workload.metadata
        status = workload.status
        spec = workload.spec
        owner_references = metadata.owner_references if metadata else None
        owners = tuple(
            OwnerReference(
                kind=owner.kind or "unknown",
                name=owner.name or "unknown",
                controller=owner.controller,
            )
            for owner in (owner_references or [])
        )
        status_values = _workload_status(kind, spec, status)
        return WorkloadInfo(
            kind=kind,
            name=metadata.name if metadata and metadata.name else name,
            owners=owners,
            status=status_values,
        )

    def list_warning_events(
        self, namespace: str, object_kind: str, object_name: str, limit: int = 10
    ) -> list[WarningEvent]:
        """Return the most recent Warning events for one object."""
        field_selector = (
            f"involvedObject.kind={object_kind},"
            f"involvedObject.name={object_name},type=Warning"
        )
        response = self._api.list_namespaced_event(
            namespace=namespace, field_selector=field_selector, limit=limit
        )
        events = [
            _warning_event(event)
            for event in (response.items or [])
            if event.type == "Warning"
        ]
        return sorted(events, key=lambda event: _event_time_key(event.timestamp), reverse=True)[
            :limit
        ]


def _workload_status(kind: str, spec: object, status: object) -> dict[str, object]:
    """Return only status fields available for the workload kind."""
    if status is None:
        return {}
    fields: dict[str, object] = {}
    if kind == "Deployment":
        desired = getattr(spec, "replicas", None) if spec is not None else None
        _add_if_available(fields, "desired_replicas", desired)
        names: tuple[str, ...] = (
            "ready_replicas",
            "available_replicas",
            "updated_replicas",
            "unavailable_replicas",
        )
    elif kind == "ReplicaSet":
        names = ("replicas", "ready_replicas", "available_replicas")
    elif kind == "StatefulSet":
        names = (
            "replicas",
            "ready_replicas",
            "current_replicas",
            "updated_replicas",
            "available_replicas",
        )
    elif kind == "DaemonSet":
        names = (
            "desired_number_scheduled",
            "current_number_scheduled",
            "number_ready",
            "updated_number_scheduled",
            "number_available",
            "number_unavailable",
        )
    else:
        names = ("active", "succeeded", "failed", "ready")
    for name in names:
        _add_if_available(fields, name, getattr(status, name, None))
    conditions = getattr(status, "conditions", None)
    if conditions:
        fields["conditions"] = [
            _condition_data(condition)
            for condition in conditions
        ]
    return fields


def _condition_data(condition: object) -> dict[str, object]:
    data: dict[str, object] = {}
    for key in ("type", "status", "reason", "message"):
        value = getattr(condition, key, None)
        if value is not None:
            data[key] = value
    last_update = getattr(condition, "last_update_time", None)
    if last_update is not None:
        data["last_update_time"] = last_update.isoformat()
    return data


def _add_if_available(
    target: dict[str, object], key: str, value: object | None
) -> None:
    if value is not None:
        target[key] = value


def _warning_event(event: object) -> WarningEvent:
    """Convert a Kubernetes event to the internal warning-event model."""
    timestamp = next(
        (
            value
            for value in (
                getattr(event, "event_time", None),
                getattr(event, "last_timestamp", None),
                getattr(event, "first_timestamp", None),
                getattr(getattr(event, "metadata", None), "creation_timestamp", None),
            )
            if value is not None
        ),
        None,
    )
    return WarningEvent(
        reason=getattr(event, "reason", None),
        message=getattr(event, "message", None),
        timestamp=timestamp.isoformat() if timestamp is not None else None,
    )


def _event_time_key(timestamp: str | None) -> datetime:
    if timestamp is None:
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_pod_reader(
    kubeconfig: Path | None = None, context: str | None = None
) -> KubernetesPodReader:
    """Load kubeconfig and construct the official-client adapter."""
    config.load_kube_config(  # type: ignore[attr-defined, no-untyped-call]
        config_file=str(kubeconfig) if kubeconfig is not None else None,
        context=context,
    )
    return KubernetesPodReader(
        client.CoreV1Api(), client.AppsV1Api(), client.BatchV1Api()
    )
