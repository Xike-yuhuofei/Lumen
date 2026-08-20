"""Sandbox runner sidecar: a tiny HTTP service that executes untrusted shell.

Runs in its own least-privileged container, isolated from the main app. The
main app talks to it via :class:`lumen.shared.sandbox.backends.RunnerSidecarBackend`,
pointed at it through ``LUMEN_SANDBOX_RUNNER_URL``.
"""
