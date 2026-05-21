# Contributing

Thank you for your interest in `ha-state-archive`.

This project is infrastructure-oriented software focused on archival integrity, deterministic processing and governance workflows for Home Assistant environments.

The project prioritizes:

- determinism;
- reproducibility;
- observability;
- bounded outputs;
- operational safety;
- architectural coherence.

---

## Before contributing

Please open an issue before submitting large changes or architectural modifications.

The project intentionally maintains strong architectural boundaries and not all feature proposals align with its design goals.

---

## Development principles

Contributions should preserve the following principles:

- immutable archive handling;
- observational-only auditing;
- quarantine-before-purge workflows;
- infrastructure/runtime separation;
- deterministic processing;
- bounded and auditable outputs;
- explicit failure handling;
- no hidden side effects.

---

## Pull requests

Pull requests should:

- remain focused and scoped;
- avoid unrelated refactors;
- preserve existing contracts and CLI behavior;
- include documentation updates when relevant;
- include tests when behavior changes.

Large architectural rewrites are unlikely to be accepted without prior discussion.

---

## Coding style

The project favors:

- explicit logic over implicit magic;
- predictable filesystem behavior;
- defensive validation;
- operational clarity;
- minimal hidden state.

Avoid introducing unnecessary abstractions or framework-heavy patterns.

---

## Testing

Before submitting a pull request:

```bash
pytest
```

Validate CLI behavior where applicable.

---

## Security-sensitive areas

Extra care is required for code touching:

- retention;
- purge logic;
- filesystem traversal;
- archive extraction;
- MQTT publication;
- subprocess execution.

Safety and traceability take precedence over convenience.

---

## Documentation

Documentation is considered part of the project itself, not an optional addition.

Behavioral or architectural changes should be reflected in the relevant documentation files.

---

## Project philosophy

`ha-state-archive` is not intended to become a Home Assistant addon or an in-runtime automation layer.

The project intentionally operates as an external infrastructure-side governance and archival platform.