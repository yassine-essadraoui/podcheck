from podcheck.health import ContainerInfo, PodInfo, inspect_pod


def make_pod(
    phase: str | None, ready: bool | None = True, name: str = "demo"
) -> PodInfo:
    containers = (
        (ContainerInfo(name="app", ready=ready, restart_count=0),)
        if ready is not None
        else ()
    )
    return PodInfo(
        namespace="default",
        name=name,
        phase=phase,
        containers=containers,
    )


def test_running_ready_pod_is_healthy() -> None:
    result = inspect_pod(make_pod("Running"))
    assert result.healthy
    assert result.reasons == ()


def test_non_running_pod_is_unhealthy() -> None:
    result = inspect_pod(make_pod("Pending"))
    assert not result.healthy
    assert result.reasons == ("phase is Pending",)


def test_unready_container_is_unhealthy() -> None:
    result = inspect_pod(make_pod("Running", ready=False))
    assert result.reasons == ("container app is not ready",)


def test_missing_phase_is_reported_as_unknown() -> None:
    result = inspect_pod(make_pod(None, ready=None))
    assert result.reasons == ("phase is unknown",)
