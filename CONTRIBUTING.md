# Contributing

All changes should preserve these invariants:

1. The Pi remains a perception-only device.
2. Failure or stale data results in RAVE becoming unavailable.
3. Configuration and protocol changes are versioned.
4. Runtime dependencies and hardware assumptions are pinned and documented.
5. Mock components are clearly labeled until validated on hardware.

Run `pytest` and `ruff check edge tests` before opening a pull request.
