# Project instructions

## Product
`podcheck` is a read-only Python CLI that connects to kubernetes using a kubeconfig, retrieves pods, identifies unhealthy pods and explains why.

## Stack
- Python 3.12+
- Click for CLI
- Official Kubernetes Python client
- pytest, ruff, mypy

## Safety rules
- Read-only: no delete, exec, apply, scale, restart, or patch operations
- Do not request or access Secrets
- Use least-privilege access
- Unit tests must use mocked Kubernetes API responses
- Do not require a live cluster for unit tests

## Workflow
1. Inspect relevant files.
2. Propose an architecture and implementation plan first.
3. wait for approval before editing.
4. Make small, testable changes.
5. Activate the project virtual environment and run `pytest`, `ruff check .`, and `mypy src`.
6. Summarize the diff, risks and follow-up work.

## Environment
- Use an isolated project virtual environment for development and checks.
- Activate it before running Python tools.

## Required checks
Run these commands from the repository root:

pytest
ruff check .
mypy src
