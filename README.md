# RAVE Deployment

> Development scaffolding only. RAVE is not road-ready, production-ready, or able to
> control a vehicle.

RAVE (Rear Awareness Vision Engine) is a proposed Raspberry Pi edge-perception
appliance for a rear-facing camera. This repository currently defines safety
boundaries and exercises configuration, health-reporting, packaging, and deployment
scaffolding.

## Current status

What works today:

- Python configuration parsing and validation;
- structured development-host and Raspberry Pi readiness checks;
- an explicitly enabled synthetic-message loop for local development;
- unit tests, linting, and lightweight repository CI checks;
- example service, packaging, image, and setup-UI files.

Mock scaffolding:

- detections are synthetic and JSON is used only for internal mock/debug output;
- the setup UI, installer, OS image, Debian packaging, networking configuration, and
  systemd units are incomplete scaffolding;
- `protocol/rave.proto` is a proposed future wire schema only. No bindings are
  generated or used.

Planned, but not implemented:

- camera capture and an approved production camera;
- Hailo inference, tracking, and validated models/crops/thresholds;
- networking, transport, authentication, replay protection, and pairing;
- model download/update and signed release images;
- a Comma-side receiver or integration.

There is **no approved production camera** and RAVE currently has **no Comma
receiver**. Values in the example configuration and candidate hardware documents
are unvalidated.

## Enforced safety boundary

The Raspberry Pi is a stand-alone perception sensor. It must never access Panda,
vehicle CAN, or vehicle-control interfaces, and Pi software must not include Panda or
CAN dependencies. Any future Comma receiver must be a separately reviewed component.
Loss or invalidity of any RAVE input must make RAVE unavailable.

## Development-only mock

Install development dependencies in a virtual environment, then run checks:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
rave config-check --config config/rave.toml.example
rave doctor --config config/rave.toml.example
pytest
```

The synthetic loop requires both the example configuration's explicit development
mode and a command-line acknowledgement:

```bash
rave-edge --config config/rave.toml.example --development-mock
```

Without that flag it exits immediately. The installed systemd service deliberately
does not pass the flag, has no automatic restart policy, and has no install target.
It therefore remains inactive by default and cannot masquerade as a production
runtime.

## Repository map

```text
edge/                 Configuration, health checks, and mock-only runtime
protocol/             Proposed future wire schema (source only)
setup-ui/             First-boot UI scaffolding
image/                OS image configuration scaffolding
packaging/            Debian packaging scaffolding
hardware/             Candidate hardware and wiring notes
models/               Model bundle format examples; no weights
scripts/              Installer and diagnostics scaffolding
systemd/              Inactive-by-capability service definitions
tests/                Unit tests
.github/workflows/     CI and manual release-workflow placeholder
```
