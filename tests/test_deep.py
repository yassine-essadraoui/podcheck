from unittest.mock import Mock

from click.testing import CliRunner
from kubernetes.client.exceptions import ApiException

from podcheck import cli
from podcheck.deep import WarningEvent, WorkloadInfo, enrich_pod
from podcheck.health import ContainerInfo, OwnerReference, PodInfo, inspect_pod


def failing_pod(owners: tuple[OwnerReference, ...] = ()) -> PodInfo:
    return PodInfo(
        namespace="team-a",
        name="demo",
        phase="Running",
        containers=(ContainerInfo("app", False, 2),),
        owners=owners,
    )


def workload(
    kind: str,
    name: str,
    owners: tuple[OwnerReference, ...] = (),
    status: dict[str, object] | None = None,
) -> WorkloadInfo:
    return WorkloadInfo(kind, name, owners, status or {})


def test_resolves_replicaset_to_deployment_and_sorts_timeline() -> None:
    reader = Mock()
    reader.read_workload.side_effect = [
        workload("ReplicaSet", "demo-abc", (OwnerReference("Deployment", "demo"),)),
        workload("Deployment", "demo", status={"ready_replicas": 1}),
    ]
    reader.list_warning_events.side_effect = [
        [WarningEvent("BackOff", "container restarting", "2026-05-02T10:00:00+00:00")],
        [WarningEvent("ScalingReplicaSet", "scaled replicas", "2026-05-02T09:00:00+00:00")],
    ]
    pod = failing_pod((OwnerReference("ReplicaSet", "demo-abc", True),))

    context = enrich_pod(reader, inspect_pod(pod))

    assert [(item.kind, item.name) for item in context.owner_chain] == [
        ("ReplicaSet", "demo-abc"),
        ("Deployment", "demo"),
    ]
    assert context.workload is not None
    assert context.workload.kind == "Deployment"
    assert [event.reason for event in context.timeline] == [
        "ScalingReplicaSet",
        "BackOff",
    ]


def test_pod_without_owner_uses_pod_health_as_diagnosis() -> None:
    reader = Mock()
    reader.list_warning_events.return_value = []

    context = enrich_pod(reader, inspect_pod(failing_pod()))

    assert context.owner_chain == ()
    assert context.workload is None
    assert context.diagnosis == "Pod is unhealthy: container app is not ready"
    reader.read_workload.assert_not_called()


def test_deployment_unavailable_replicas_are_diagnosed() -> None:
    reader = Mock()
    reader.read_workload.return_value = workload(
        "Deployment", "demo", status={"unavailable_replicas": 2}
    )
    reader.list_warning_events.return_value = []

    context = enrich_pod(
        reader,
        inspect_pod(failing_pod((OwnerReference("Deployment", "demo", True),))),
    )

    assert context.diagnosis == "Deployment has 2 unavailable replicas."


def test_deployment_progressing_condition_is_diagnosed() -> None:
    reader = Mock()
    reader.read_workload.return_value = workload(
        "Deployment",
        "demo",
        status={
            "conditions": [
                {
                    "type": "Progressing",
                    "status": "False",
                    "reason": "ProgressDeadlineExceeded",
                }
            ]
        },
    )
    reader.list_warning_events.return_value = []

    context = enrich_pod(
        reader,
        inspect_pod(failing_pod((OwnerReference("Deployment", "demo"),))),
    )

    assert "Progressing condition is False" in context.diagnosis
    assert "ProgressDeadlineExceeded" in context.diagnosis


def test_event_api_failure_is_recorded_and_does_not_abort() -> None:
    reader = Mock()
    reader.list_warning_events.side_effect = ApiException(status=403, reason="Forbidden")

    context = enrich_pod(reader, inspect_pod(failing_pod()))

    assert context.pod_events == ()
    assert len(context.errors) == 1
    assert "Warning events for Pod demo" in context.errors[0]
    assert "container app is not ready" in context.diagnosis


def test_no_warning_events_produce_empty_timeline() -> None:
    reader = Mock()
    reader.list_warning_events.return_value = []

    context = enrich_pod(reader, inspect_pod(failing_pod()))

    assert context.pod_events == ()
    assert context.workload_events == ()
    assert context.timeline == ()


def test_deep_disabled_does_not_add_deep_json_or_call_lookups(
    monkeypatch: object,
) -> None:
    reader = Mock()
    reader.list_pods.return_value = [failing_pod()]
    monkeypatch.setattr(cli, "load_pod_reader", lambda *_args: reader)  # type: ignore[attr-defined]

    result = CliRunner().invoke(
        cli.main, ["--namespace", "team-a", "--output", "json"]
    )

    assert result.exit_code == 1
    assert '"deep"' not in result.output
    reader.read_workload.assert_not_called()
    reader.list_warning_events.assert_not_called()
