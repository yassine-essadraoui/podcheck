# podcheck

`podcheck` is a read-only command-line tool for finding unhealthy Kubernetes
pods. It loads a kubeconfig, lists pods in a selected scope, and reports pods
whose phase is not `Running` or that contain an unready container.

## Install

From the repository root, install the package:

```bash
python -m pip install .
```

For development, install it in editable mode with the development tools:

```bash
python -m pip install -e ".[dev]"
```

It can also be installed directly from:

```bash
python -m pip install "git+https://github.com/yassine-essadraoui/podcheck.git"
```

To keep the installation isolated, create and activate a virtual environment
before installing:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Usage

Choose exactly one namespace scope:

```bash
podcheck --namespace default
podcheck --all-namespaces
```

The default output is text. Use `--output json` for machine-readable output,
`--failing-only` to omit healthy pods, or `--deep` to add workload and event
context for failing pods:

```bash
podcheck --namespace payments --failing-only
podcheck --all-namespaces --output json
podcheck --namespace payments --deep --output json
```

Kubeconfig options can select a different file or context:

```bash
podcheck --namespace payments \
  --kubeconfig /path/to/kubeconfig \
  --context staging
```

After installation, run the `podcheck` command from the active environment:

```bash
podcheck --namespace default
```

The installed Python module can also be run directly:

```bash
python -m podcheck.cli --namespace default
```

## Deep mode

`--deep` enriches failing pods with owner-chain and workload status information.
It follows ReplicaSet owners to Deployments and supports StatefulSets,
DaemonSets, and Jobs. It also collects up to 10 recent Warning events for each
failing pod and its identified workload, then orders them into a timeline.
Diagnosis text is produced from the collected status and event evidence using
fixed rules; it does not use an LLM. Enrichment lookup errors are reported in
the deep result without discarding the base pod report.

Without `--deep`, the CLI does not perform workload or event lookups. Existing
pod report fields remain the same; deep mode adds a `deep` object to failing
pods in JSON output.

## Exit codes

- `0` — no unhealthy pods were found.
- `1` — one or more unhealthy pods were found.
- `2` — invalid arguments or a kubeconfig/Kubernetes API error prevented the
  pod listing.

## Access and safety

The tool only makes Kubernetes read requests. Pod listing requires `list`
access to pods in the requested namespaces. Deep mode additionally needs
`list` access to events and `get` access to ReplicaSets, Deployments,
StatefulSets, DaemonSets, and Jobs as applicable. For `--all-namespaces`, pod
listing must be allowed across namespaces. Exact permissions can be scoped to
the namespaces the user needs to inspect.

Reports include read-only follow-up commands such as:

```bash
kubectl describe pod example-pod -n default
```

The tool does not access Secrets, read logs, execute commands in containers,
or change cluster resources.
