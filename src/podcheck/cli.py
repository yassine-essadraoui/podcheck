"""Command-line interface for podcheck."""

from pathlib import Path

import click
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException

from podcheck.deep import enrich_report
from podcheck.health import inspect_pods
from podcheck.kubernetes import PodReader, load_pod_reader
from podcheck.report import render_json, render_text


class PodcheckError(click.ClickException):
    """Kubernetes setup or API failure, reported with exit code 2."""

    exit_code = 2


@click.command()
@click.option(
    "--kubeconfig", type=click.Path(path_type=Path, exists=True, dir_okay=False)
)
@click.option("--context", "context_name", help="Kubeconfig context to use.")
@click.option("--namespace", help="Inspect pods in this namespace.")
@click.option("--all-namespaces", is_flag=True, help="Inspect pods in every namespace.")
@click.option("--failing-only", is_flag=True, help="Show only unhealthy pods.")
@click.option("--deep", "deep_mode", is_flag=True, help="Add workload and event context.")
@click.option(
    "--output",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
)
def main(
    kubeconfig: Path | None,
    context_name: str | None,
    namespace: str | None,
    all_namespaces: bool,
    failing_only: bool,
    deep_mode: bool,
    output: str,
) -> None:
    """Identify unhealthy Kubernetes pods without changing cluster state."""
    if (namespace is None) == (not all_namespaces):
        raise click.UsageError("choose exactly one of --namespace or --all-namespaces")

    try:
        reader: PodReader = load_pod_reader(kubeconfig, context_name)
        pods = reader.list_pods(namespace=None if all_namespaces else namespace)
    except (ApiException, ConfigException) as error:
        raise PodcheckError(f"Kubernetes error: {error}") from error

    scope = "all namespaces" if all_namespaces else f"namespace {namespace}"
    report = inspect_pods(pods, scope, failing_only=failing_only)
    if deep_mode:
        report = enrich_report(reader, report)
    click.echo(render_json(report) if output == "json" else render_text(report))
    if any(not pod.healthy for pod in report.pods):
        click.get_current_context().exit(1)


if __name__ == "__main__":
    main()
