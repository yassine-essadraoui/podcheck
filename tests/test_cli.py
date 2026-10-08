import json
from unittest.mock import Mock

from click.testing import CliRunner
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException

from podcheck import cli
from podcheck.health import ContainerInfo, PodInfo


def healthy_pod(name: str = "healthy") -> PodInfo:
    return PodInfo(
        namespace="team-a",
        name=name,
        phase="Running",
        containers=(ContainerInfo("app", True, 0),),
    )


def unhealthy_pod(name: str = "demo") -> PodInfo:
    return PodInfo(
        namespace="team-a",
        name=name,
        phase="Running",
        containers=(ContainerInfo("app", False, 3),),
    )


def set_reader(monkeypatch: object, pods: list[PodInfo]) -> Mock:
    reader = Mock()
    reader.list_pods.return_value = pods
    monkeypatch.setattr(cli, "load_pod_reader", lambda *_args: reader)  # type: ignore[attr-defined]
    return reader


def test_namespace_json_output_includes_health_details(monkeypatch: object) -> None:
    reader = set_reader(monkeypatch, [healthy_pod(), unhealthy_pod()])
    result = CliRunner().invoke(
        cli.main,
        ["--namespace", "team-a", "--output", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    failing = payload["pods"][1]
    assert failing["namespace"] == "team-a"
    assert failing["name"] == "demo"
    assert failing["phase"] == "Running"
    assert failing["unready_containers"] == ["app"]
    assert failing["containers"][0]["restart_count"] == 3
    assert failing["reasons"] == ["container app is not ready"]
    assert failing["follow_up"] == "kubectl describe pod demo -n team-a"
    reader.list_pods.assert_called_once_with(namespace="team-a")


def test_failing_only_excludes_healthy_pods(monkeypatch: object) -> None:
    set_reader(monkeypatch, [healthy_pod(), unhealthy_pod()])
    result = CliRunner().invoke(
        cli.main,
        ["--namespace", "team-a", "--output", "json", "--failing-only"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert [pod["name"] for pod in payload["pods"]] == ["demo"]


def test_healthy_report_exits_zero(monkeypatch: object) -> None:
    set_reader(monkeypatch, [healthy_pod()])
    result = CliRunner().invoke(cli.main, ["--namespace", "team-a"])
    assert result.exit_code == 0
    assert "HEALTHY team-a/healthy" in result.output


def test_all_namespaces_uses_adapter_without_namespace(monkeypatch: object) -> None:
    reader = set_reader(monkeypatch, [])
    result = CliRunner().invoke(cli.main, ["--all-namespaces"])

    assert result.exit_code == 0
    assert "Pod health report (all namespaces)" in result.output
    reader.list_pods.assert_called_once_with(namespace=None)


def test_scope_is_required() -> None:
    result = CliRunner().invoke(cli.main, [])
    assert result.exit_code == 2
    assert "choose exactly one" in result.output


def test_scope_options_are_mutually_exclusive() -> None:
    result = CliRunner().invoke(cli.main, ["--all-namespaces", "--namespace", "team-a"])
    assert result.exit_code == 2
    assert "choose exactly one" in result.output


def test_api_error_exits_two(monkeypatch: object) -> None:
    reader = Mock()
    reader.list_pods.side_effect = ApiException(status=403, reason="Forbidden")
    monkeypatch.setattr(cli, "load_pod_reader", lambda *_args: reader)  # type: ignore[attr-defined]

    result = CliRunner().invoke(cli.main, ["--namespace", "team-a"])

    assert result.exit_code == 2
    assert "Kubernetes error" in result.output


def test_configuration_error_exits_two(monkeypatch: object) -> None:
    monkeypatch.setattr(
        cli,
        "load_pod_reader",
        Mock(side_effect=ConfigException("invalid kubeconfig")),
    )  # type: ignore[attr-defined]

    result = CliRunner().invoke(cli.main, ["--namespace", "team-a"])

    assert result.exit_code == 2
    assert "invalid kubeconfig" in result.output
