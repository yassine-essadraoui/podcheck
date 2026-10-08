from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from kubernetes.client import (
    V1ContainerStatus,
    V1ObjectMeta,
    V1Pod,
    V1PodList,
    V1PodStatus,
)

from podcheck import kubernetes
from podcheck.health import ContainerInfo, PodInfo


def raw_pod() -> V1Pod:
    return V1Pod(
        metadata=V1ObjectMeta(name="demo", namespace="team-a"),
        status=V1PodStatus(
            phase="Running",
            container_statuses=[
                V1ContainerStatus(
                    name="app",
                    ready=False,
                    restart_count=3,
                    image="app",
                    image_id="app-id",
                )
            ],
        ),
    )


def test_namespace_listing_calls_official_client_and_converts_response() -> None:
    api = Mock()
    api.list_namespaced_pod.return_value = V1PodList(items=[raw_pod()])
    reader = kubernetes.KubernetesPodReader(api)

    result = reader.list_pods(namespace="team-a")

    assert result == [
        PodInfo(
            namespace="team-a",
            name="demo",
            phase="Running",
            containers=(ContainerInfo("app", False, 3),),
        )
    ]
    api.list_namespaced_pod.assert_called_once_with(namespace="team-a")
    api.list_pod_for_all_namespaces.assert_not_called()


def test_all_namespace_listing_uses_official_client_method() -> None:
    api = Mock()
    api.list_pod_for_all_namespaces.return_value = V1PodList(items=[raw_pod()])
    reader = kubernetes.KubernetesPodReader(api)

    result = reader.list_pods()

    assert result[0].name == "demo"
    api.list_pod_for_all_namespaces.assert_called_once_with()
    api.list_namespaced_pod.assert_not_called()


def test_loader_passes_optional_kubeconfig_and_context(monkeypatch: object) -> None:
    api = Mock()
    monkeypatch.setattr(kubernetes.config, "load_kube_config", Mock())  # type: ignore[attr-defined]
    monkeypatch.setattr(kubernetes.client, "CoreV1Api", Mock(return_value=api))  # type: ignore[attr-defined]
    kubeconfig = Path("/tmp/test-kubeconfig")

    reader = kubernetes.load_pod_reader(kubeconfig, "test-context")

    kubernetes.config.load_kube_config.assert_called_once_with(  # type: ignore[attr-defined]
        config_file=str(kubeconfig), context="test-context"
    )
    assert isinstance(reader, kubernetes.KubernetesPodReader)


def test_warning_events_are_filtered_sorted_and_limited() -> None:
    api = Mock()
    api.list_namespaced_event.return_value = SimpleNamespace(
        items=[
            SimpleNamespace(
                type="Warning",
                reason=f"Warning{i}",
                message="test",
                event_time=datetime(2026, 1, 1, hour=i, tzinfo=UTC),
            )
            for i in range(11)
        ]
        + [
            SimpleNamespace(
                type="Normal",
                reason="Ignored",
                message="normal event",
                event_time=datetime(2026, 1, 2, tzinfo=UTC),
            )
        ]
    )
    reader = kubernetes.KubernetesPodReader(api)

    events = reader.list_warning_events("team-a", "Pod", "demo")

    assert len(events) == 10
    assert events[0].reason == "Warning10"
    assert events[-1].reason == "Warning1"
    api.list_namespaced_event.assert_called_once_with(
        namespace="team-a",
        field_selector="involvedObject.kind=Pod,involvedObject.name=demo,type=Warning",
        limit=10,
    )
