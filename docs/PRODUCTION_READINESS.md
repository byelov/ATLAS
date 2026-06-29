# Production readiness

ATLAS separates checks by whether they can run on a normal development
machine or require containers, a model, or specific hardware.

Current capability classifications are recorded in
[CAPABILITIES.md](CAPABILITIES.md).

## Developer gate

Run the default gate from the repository root:

```bash
python scripts/production-readiness.py
```

The required checks cover test integrity, Python compilation and unit tests,
and Go race tests and vet for the proxy and TUI. They do not require a GPU,
model download, or running ATLAS services.

The developer gate includes contract tests for V3 language-aware syntax
verification and sandbox overlay behavior. Full project build-command
qualification still belongs to the container and release tiers because it
depends on the selected project's dependencies and toolchain state.

Optional checks run when their tools are installed. Missing optional tools are
reported as `unavailable`, not as successful checks. A missing tool becomes a
failure when its gate is selected explicitly:

```bash
python scripts/production-readiness.py --only ruff
python scripts/production-readiness.py --only compose
```

Use `--list` to see the available gates and `--json` for machine-readable
results. CI runs the same named gates after installing their dependencies.

## Test tiers

| Tier | Purpose | Hardware or services |
|---|---|---|
| Hermetic | Unit, static, race, and configuration checks | No GPU, model, or running services |
| Local integration | HTTP, SSE, cancellation, and process lifecycle | Locally built binaries; no model where possible |
| Container integration | Compose networking, health, filesystem mounts, and sandbox behavior | Docker |
| Hardware integration | Real inference, embeddings, Lens compatibility, and accelerator behavior | Supported accelerator and registry model |
| Release qualification | Clean install plus all applicable tiers and artifact checks | Declared release hardware matrix |

Hardware-dependent checks must name the model and accelerator used. For the
canonical Apple Silicon path, use the registry entry selected by `atlas model
recommend`; production qualification should record the exact registry name,
GGUF hash status, backend, context size, and service image digests.

## Skip policy

- A required dependency missing from a selected gate is a failure.
- An optional dependency missing from the default developer gate is
  `unavailable`.
- A hardware test skipped because the required hardware is absent is
  `unavailable`; it does not count as a pass.
- A supported release cannot be qualified while a required release gate is
  failed or unavailable.
