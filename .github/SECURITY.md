# Security Policy

## Supported versions

Security fixes are provided only for the latest public release.

Older releases may contain known architectural or security limitations and should not be considered supported for production usage.

---

## Reporting a vulnerability

Please do not open public GitHub issues for security-sensitive reports.

Instead, use GitHub private vulnerability reporting:

- Security tab
- "Report a vulnerability"

If GitHub private reporting is unavailable, contact the maintainer directly through GitHub.

---

## Scope

This project is an infrastructure-side archival and governance platform for Home Assistant environments.

Security-sensitive areas include:

- backup extraction;
- archive retention and purge workflows;
- MQTT publication;
- filesystem traversal;
- path validation;
- deletion safety;
- external command execution;
- credential handling.

Reports involving unsafe deletion, path traversal, quarantine escape or credential exposure are treated with high priority.

---

## Security model

The project intentionally separates:

- Home Assistant runtime;
- infrastructure-side archival processing;
- governance and audit layers.

The software is designed to operate outside Home Assistant itself, typically on NAS systems, servers or CI runners.

The project does not expose network services by default.

---

## Responsible disclosure

Please allow reasonable time for investigation and remediation before public disclosure.

Coordinated disclosure is appreciated.