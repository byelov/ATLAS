# Capability status

This file defines the support level and minimum verification tier for ATLAS
capabilities. Roadmap items are tracked in GitHub and are not release claims.

## Status definitions

- **Supported:** part of the release contract and covered by a required gate.
- **Experimental:** usable behind an explicit option; compatibility may change.
- **Internal:** service-to-service contract, not a public client API.
- **Roadmap:** proposed or incomplete; not a release capability.

## User-facing capabilities

| Capability | Status | Minimum verification |
|---|---|---|
| Python CLI installation and command dispatch | Supported | Hermetic and install matrix |
| TUI chat, file view, pipeline view, cancellation, and feedback | Supported | Hermetic Go race tests and local integration |
| Proxy `/v1/agent`, `/events`, `/cancel`, health, readiness, and model listing | Supported | Hermetic Go race tests and local integration |
| Proxy OpenAI chat-completions passthrough | Supported | Local integration |
| Workspace file tools and sandboxed command verification | Supported | Hermetic policy tests and container integration |
| V3 candidate generation and selection for Python | Supported | Hermetic unit tests and hardware integration |
| V3 verification for non-Python syntax/toolchain checks | Supported | Hermetic unit tests and sandbox integration |
| V3 project build-command verification | Experimental | Hermetic overlay tests plus container integration |
| Model registry list, recommend, install, remove, and verify | Supported | Hermetic CLI tests and hardware integration for inference |
| Lens compatibility check, build, and retrain | Supported for registry entries with compatible artifacts | Hermetic tests and hardware integration |
| Lens and ASA artifact publishing | Experimental | Hermetic CLI tests plus maintainer review workflow |
| ASA compatibility check and build | Experimental | Hermetic tests and hardware integration |
| CUDA backend | Supported | Hardware integration |
| ROCm backend | Supported | Hardware integration |
| Apple Metal backend | Supported | Hardware integration |
| Vulkan backend | Supported | Hardware integration |
| Intel SYCL and multi-GPU backends | Roadmap | None until implemented |
| Browser or visual verification | Roadmap | None until implemented |

## Service contracts

| Service surface | Status | Notes |
|---|---|---|
| Sandbox health, languages, execute, syntax-check, shell, and background jobs | Internal | Called by proxy and V3; direct host use is a developer workflow |
| V3 generate, run, plan, and health | Internal | `/v3/generate` is the proxy integration path |
| V3 AST edit, symbol index, and complexity endpoints | Experimental internal | Tree-sitter availability determines capability |
| Geometric Lens `/v1/*` endpoints | Supported authenticated API | Requires configured local API keys |
| Geometric Lens `/internal/*` endpoints | Internal | Intended only for the ATLAS service network |
| llama-server inference, completion, embedding, and health | Upstream contract | Qualified against the pinned llama.cpp revision |

## Test tiers

The authoritative tier definitions and commands are in
[PRODUCTION_READINESS.md](PRODUCTION_READINESS.md). A feature is not promoted to
Supported until its required tier is automated and passing on representative
hardware where applicable.
