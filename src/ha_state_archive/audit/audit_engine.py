from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from ha_state_archive.audit.declaration_extractor import (
    DeclaredEntity,
    ExtractionResult,
    RUNTIME_YAML_AUTHORITY,
    _ha_slugify,
)
from ha_state_archive.audit.reference_extractor import (
    EntityReference,
    ReferenceResult,
)
from ha_state_archive.audit.registry_reader import EntityRecord


# ---------------------------------------------------------------------------
# V1 metadata
# ---------------------------------------------------------------------------

__version__ = "1.1.1"
# 1.0.0 = first frozen NAS CLI release.
# 1.1.0 = canonical resolution pipeline, legacy platforms recognised.
# 1.1.1 = multiple authority classes (registry / runtime_yaml),
#         separation of anomalies and architectural observations.


def _load_audit_config(config_path: Path) -> dict:
    import yaml
    if not config_path.exists():
        return {}
    try:
        with config_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _build_system_entity_set(config: dict) -> frozenset[str]:
    entries = config.get("system_entities", [])
    return frozenset(
        e["entity_id"].strip() for e in entries
        if isinstance(e, dict)
        and isinstance(e.get("entity_id"), str)
        and e["entity_id"].strip()
    )


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

AnomalyType = Literal[
    "declared_not_in_registry",
    "declared_outside_registry",
    "registry_not_declared",
    "declared_duplicate",
    "registry_duplicate",
    "broken_reference",
    "non_canonical_entity_id_case",
]

ObservationType = Literal[
    "runtime_yaml_observation",
]

Severity = Literal["P0", "P1", "P2", "P3"]
Confidence = Literal["high", "medium", "low"]


@dataclass
class AuditAnomaly:
    entity_id: str
    anomaly_type: AnomalyType
    severity: Severity
    confidence: Confidence
    evidence: list[str]
    notes: str


@dataclass
class AuditObservation:
    """V1.1.1 architectural observation — outside the severity scale.
    Never counted in total_anomalies (see contract V1.1.1 §7.2)."""
    entity_id: str
    observation_type: ObservationType
    confidence: Confidence
    evidence: list[str]
    notes: str


@dataclass
class AuditResult:
    anomalies: list[AuditAnomaly] = field(default_factory=list)
    observations: list[AuditObservation] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _registry_index(
    records: list[EntityRecord],
) -> tuple[dict[str, EntityRecord], list[str]]:
    index: dict[str, EntityRecord] = {}
    duplicates: list[str] = []
    for record in records:
        if record.entity_id in index:
            duplicates.append(record.entity_id)
        index[record.entity_id] = record
    return index, duplicates


def _declared_high_index(
    extraction: ExtractionResult,
) -> dict[str, list[DeclaredEntity]]:
    index: dict[str, list[DeclaredEntity]] = {}
    for e in extraction.entities:
        if e.confidence == "high" and e.entity_id:
            index.setdefault(e.entity_id, []).append(e)
    return index


def _canonical_key(entity_id: str) -> str | None:
    if "." not in entity_id:
        return None

    domain, object_id = entity_id.split(".", 1)
    canonical_object_id = _ha_slugify(object_id)

    if not canonical_object_id:
        return None

    return f"{domain}.{canonical_object_id}"


def _registry_canonical_index(
    registry_idx: dict[str, EntityRecord],
) -> dict[str, str]:
    index: dict[str, str] = {}

    for entity_id in registry_idx.keys():
        key = _canonical_key(entity_id)

        if key is None:
            continue

        index.setdefault(key, entity_id)

    return index


def _find_declared_duplicates(extraction: ExtractionResult) -> dict[str, int]:
    counts = Counter(
        e.entity_id
        for e in extraction.entities
        if e.confidence == "high" and e.entity_id is not None
    )
    return dict(sorted((k, v) for k, v in counts.items() if v > 1))


# V1 high-confidence declarative scope
# input_button and utility_meter are excluded: not reliably covered
_HIGH_CONFIDENCE_PLATFORMS = {
    "input_boolean",
    "input_text",
    "input_number",
    "input_datetime",
    "input_select",
    "counter",
    "timer",
}


def _severity_declared_not_in_registry(entity_id: str) -> Severity:
    domain = entity_id.split(".")[0] if "." in entity_id else ""
    if domain in {"input_boolean", "input_number", "input_text"}:
        return "P0"
    return "P1"


def _severity_registry_not_declared(record: EntityRecord) -> Severity:
    if record.disabled_by or record.hidden_by:
        return "P2"
    return "P1"


def _severity_broken_reference(refs: list[EntityReference]) -> Severity:
    contexts = {r.context_type for r in refs}
    if contexts & {"automation", "script"}:
        return "P0"
    if "template" in contexts:
        return "P1"
    return "P2"


# ---------------------------------------------------------------------------
# Cross-checks
# ---------------------------------------------------------------------------

def _check_declared_not_in_registry(
    declared_index: dict[str, list[DeclaredEntity]],
    registry_idx: dict[str, EntityRecord],
    result: AuditResult,
) -> None:
    """V1.1.1 — discrimination by authority_class (see contract §6.2).

    - Declarations from runtime_yaml_authority platforms → runtime_yaml_observation
      (outside total_anomalies, outside the severity scale).
    - Otherwise → standard declared_not_in_registry (P0/P1).

    declared_outside_registry remains defined in the model (§7.3) but no
    path emits it in V1.1.1: residual case not observed in practice.
    """
    for entity_id, declarations in sorted(declared_index.items()):
        if entity_id in registry_idx:
            continue

        files = sorted({str(d.file_path) for d in declarations})

        runtime_yaml_only = all(
            d.authority_class == RUNTIME_YAML_AUTHORITY
            for d in declarations
        )

        if runtime_yaml_only:
            platforms = sorted({d.platform for d in declarations})
            result.observations.append(AuditObservation(
                entity_id=entity_id,
                observation_type="runtime_yaml_observation",
                confidence="high",
                evidence=[
                    f"Platform(s): {', '.join(platforms)}",
                    *[f"Declared in: {f}" for f in files],
                ],
                notes=(
                    "Entity declared by a runtime_yaml_authority platform "
                    f"({', '.join(platforms)}). Absence from the registry is consistent "
                    "with the nature of the platform. No action required."
                ),
            ))
            continue

        result.anomalies.append(AuditAnomaly(
            entity_id=entity_id,
            anomaly_type="declared_not_in_registry",
            severity=_severity_declared_not_in_registry(entity_id),
            confidence="high",
            evidence=[f"Declared in: {f}" for f in files],
            notes=(
                "Entity declared in high-confidence YAML but missing from the registry. "
                "Likely causes: file not loaded by HA, syntax error, "
                "entity never activated, or declaration not recognised by the extractor."
            ),
        ))


def _check_registry_not_declared(
    declared_index: dict[str, list[DeclaredEntity]],
    registry_records: list[EntityRecord],
    result: AuditResult,
) -> None:
    for record in sorted(registry_records, key=lambda r: r.entity_id):
        if record.platform not in _HIGH_CONFIDENCE_PLATFORMS:
            continue
        if record.entity_id not in declared_index:
            evidence = [f"Platform: {record.platform}"]
            if record.unique_id:
                evidence.append(f"unique_id: {record.unique_id}")
            if record.original_name:
                evidence.append(f"original_name: {record.original_name}")
            result.anomalies.append(AuditAnomaly(
                entity_id=record.entity_id,
                anomaly_type="registry_not_declared",
                severity=_severity_registry_not_declared(record),
                confidence="high",
                evidence=evidence,
                notes=(
                    "Entity present in the registry with no detected YAML declaration. "
                    "Likely causes: residue from a removed declaration, "
                    "entity created via the UI, file outside the resolver scope, "
                    "or declaration present but not recognised by the V1 extractor."
                ),
            ))


def _check_declared_duplicates(
    extraction: ExtractionResult,
    result: AuditResult,
) -> None:
    duplicates = _find_declared_duplicates(extraction)
    for entity_id, count in sorted(duplicates.items()):
        declarations = [
            e for e in extraction.entities
            if e.entity_id == entity_id and e.confidence == "high"
        ]
        files = sorted({str(d.file_path) for d in declarations})
        result.anomalies.append(AuditAnomaly(
            entity_id=entity_id,
            anomaly_type="declared_duplicate",
            severity="P0",
            confidence="high",
            evidence=[f"Declared {count}× in: {', '.join(files)}"],
            notes=(
                f"entity_id declared {count} times in YAML. "
                "The final outcome depends on load order and creates a "
                "structural ambiguity that must be corrected."
            ),
        ))


def _check_registry_duplicates(
    registry_duplicates: list[str],
    result: AuditResult,
) -> None:
    for entity_id in sorted(registry_duplicates):
        result.anomalies.append(AuditAnomaly(
            entity_id=entity_id,
            anomaly_type="registry_duplicate",
            severity="P0",
            confidence="high",
            evidence=["entity_id duplicated in core.entity_registry"],
            notes=(
                "Duplicate in the registry. Rare case, potentially a symptom "
                "of corruption or a failed migration."
            ),
        ))


def _check_broken_references(
    references: list[EntityReference],
    registry_index: dict[str, EntityRecord],
    declared_index: dict[str, list[DeclaredEntity]],
    result: AuditResult,
    system_entities: frozenset[str] = frozenset(),
) -> None:
    registry_canonical_idx = _registry_canonical_index(registry_index)

    missing: dict[str, list[EntityReference]] = {}

    for ref in references:
        if ref.entity_id in system_entities:
            continue

        if ref.entity_id in registry_index:
            continue

        canonical_key = _canonical_key(ref.entity_id)

        if canonical_key is not None and canonical_key in registry_canonical_idx:
            canonical_entity_id = registry_canonical_idx[canonical_key]

            result.anomalies.append(AuditAnomaly(
                entity_id=ref.entity_id,
                anomaly_type="non_canonical_entity_id_case",
                severity="P2",
                confidence="high",
                evidence=[
                    f"YAML reference: {ref.entity_id}",
                    f"Canonical registry entity: {canonical_entity_id}",
                    f"File: {ref.file_path}",
                    f"Context: {ref.context_type}",
                ],
                notes=(
                    "Likely functional but non-canonical reference. "
                    "Home Assistant normalisation resolves it to the registry entity. "
                    "Normalise the case or form of the entity_id in YAML."
                ),
            ))
            continue

        if ref.entity_id in declared_index:
            continue

        missing.setdefault(ref.entity_id, []).append(ref)

    for entity_id, refs in sorted(missing.items()):
        files = sorted({str(r.file_path) for r in refs})
        contexts = sorted({r.context_type for r in refs})
        count = len(refs)
        result.anomalies.append(AuditAnomaly(
            entity_id=entity_id,
            anomaly_type="broken_reference",
            severity=_severity_broken_reference(refs),
            confidence="high",
            evidence=[
                f"Referenced {count}× in {len(files)} file(s)",
                f"Contexts: {', '.join(contexts)}",
                *[f"File: {f}" for f in files[:5]],
            ],
            notes=(
                "Static reference to an entity_id absent from the full registry, "
                "not resolved by canonicalisation, and absent from the declarative index."
            ),
        ))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_audit(
    registry_local_records: list[EntityRecord],
    extraction: ExtractionResult,
    registry_all_records: list[EntityRecord] | None = None,
    ref_result: ReferenceResult | None = None,
    audit_config: dict | None = None,
) -> AuditResult:
    result = AuditResult()
    system_entities = _build_system_entity_set(audit_config or {})

    registry_local_idx, registry_local_dups = _registry_index(registry_local_records)
    declared_idx = _declared_high_index(extraction)

    _check_declared_not_in_registry(declared_idx, registry_local_idx, result)
    _check_registry_not_declared(declared_idx, registry_local_records, result)
    _check_declared_duplicates(extraction, result)
    _check_registry_duplicates(registry_local_dups, result)

    if ref_result is not None and registry_all_records is not None:
        registry_all_idx, _ = _registry_index(registry_all_records)
        _check_broken_references(
            ref_result.references,
            registry_all_idx,
            declared_idx,
            result,
            system_entities=system_entities,
        )

    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    result.anomalies.sort(key=lambda a: (
        severity_order.get(a.severity, 9),
        a.anomaly_type,
        a.entity_id,
    ))

    result.observations.sort(key=lambda o: (
        o.observation_type,
        o.entity_id,
    ))

    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for a in result.anomalies:
        by_type[a.anomaly_type] = by_type.get(a.anomaly_type, 0) + 1
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1

    by_obs_type: dict[str, int] = {}
    for o in result.observations:
        by_obs_type[o.observation_type] = by_obs_type.get(o.observation_type, 0) + 1

    result.stats = {
        "total_anomalies": len(result.anomalies),
        "total_architectural_observations": len(result.observations),
        "registry_local": len(registry_local_records),
        "registry_all": len(registry_all_records) if registry_all_records else 0,
        "declared_high_unique": len(declared_idx),
        "references_static": len(ref_result.references) if ref_result else 0,
        "references_dynamic": len(ref_result.dynamic_refs) if ref_result else 0,
        **{f"type_{k}": v for k, v in sorted(by_type.items())},
        **{f"sev_{k}": v for k, v in sorted(by_severity.items())},
        **{f"obs_type_{k}": v for k, v in sorted(by_obs_type.items())},
    }

    return result


# ---------------------------------------------------------------------------
# V1 CLI — NAS entry point
# ---------------------------------------------------------------------------

def _fail(msg: str, code: int = 1) -> None:
    """Explicit REJECT output. No silent fallbacks."""
    import sys
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _validate_ha_root(path: Path) -> None:
    if not path.exists():
        _fail(f"--ha-root not found: {path}")
    if not path.is_dir():
        _fail(f"--ha-root is not a directory: {path}")

    configuration = path / "configuration.yaml"
    if not configuration.is_file():
        _fail(f"configuration.yaml missing: {configuration}")

    registry = path / ".storage" / "core.entity_registry"
    if not registry.is_file():
        _fail(f"core.entity_registry missing: {registry}")


def _validate_config(path: Path) -> None:
    if not path.exists():
        _fail(f"--config not found: {path}")
    if not path.is_file():
        _fail(f"--config is not a file: {path}")


def _validate_report_target(path: Path) -> None:
    parent = path.parent
    if not parent.exists():
        _fail(f"report parent directory does not exist: {parent}")
    if not parent.is_dir():
        _fail(f"report parent path is not a directory: {parent}")


def _write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_verdict_json(
    path: Path,
    audit: AuditResult,
    ha_root: Path,
    executed_at: str,
) -> None:
    """Write a compact machine-readable verdict JSON for MQTT publication.

    Schema is governed by the MQTT supervision contract (docs/mqtt.md).
    Fields match the payload contract v1.0.0 required keys exactly.

    The audited_version is derived from the ha_root directory name,
    which follows the versioned directory naming convention of the ingestion
    layer (e.g. 2026-01-01_00-00_HomeAssistant).
    """
    import json

    p0_count = sum(1 for a in audit.anomalies if a.severity == "P0")

    if len(audit.anomalies) == 0:
        verdict = "ok"
    elif p0_count > 0:
        verdict = "critical"
    else:
        # P1, P2 or P3 anomalies present — all non-critical anomalies degrade the verdict.
        verdict = "degraded"

    anomaly_categories = sorted({a.anomaly_type for a in audit.anomalies})

    payload = {
        "contract_version": "1.0.0",
        "engine_version": __version__,
        "published_at": executed_at,
        "audited_version": ha_root.name,
        "verdict": verdict,
        "total_anomalies": len(audit.anomalies),
        "anomaly_categories": anomaly_categories,
        "report_path": None,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Markdown report generation
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = ("P0", "P1", "P2", "P3")

def _render_report(
    audit: AuditResult,
    ha_root: Path,
    config_path: Path,
    executed_at: str,
) -> str:
    lines: list[str] = []

    lines.append(f"# Audit Report — {executed_at}")
    lines.append("")

    lines.append("## System Metadata")
    lines.append("")
    lines.append(f"- Engine Version: `{__version__}`")
    lines.append(f"- Execution Date: {executed_at}")
    lines.append(f"- Target HA Root: `{ha_root}`")
    lines.append(f"- Configuration File: `{config_path}`")
    lines.append("")

    lines.append("## Global Statistics")
    lines.append("")
    lines.append("| Key | Value |")
    lines.append("|---|---|")
    # Sorting keys for consistent reports
    for key in sorted(audit.stats.keys()):
        lines.append(f"| `{key}` | {audit.stats[key]} |")
    lines.append("")

    by_severity = {s: 0 for s in _SEVERITY_ORDER}
    by_type: dict[str, int] = {}
    for a in audit.anomalies:
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
        by_type[a.anomaly_type] = by_type.get(a.anomaly_type, 0) + 1

    lines.append("## Severity Summary")
    lines.append("")
    lines.append("| Severity | Count |")
    lines.append("|---|---|")
    for sev in _SEVERITY_ORDER:
        lines.append(f"| **{sev}** | {by_severity[sev]} |")
    lines.append("")

    lines.append("## Anomaly Type Summary")
    lines.append("")
    if by_type:
        lines.append("| Type | Count |")
        lines.append("|---|---|")
        for anomaly_type in sorted(by_type.keys()):
            lines.append(f"| `{anomaly_type}` | {by_type[anomaly_type]} |")
    else:
        lines.append("No anomalies detected.")
    lines.append("")

    lines.append("## Actionable Anomalies")
    lines.append("")

    if not audit.anomalies:
        lines.append("No actionable anomalies detected. System integrity is high.")
        lines.append("")
    else:
        for sev in _SEVERITY_ORDER:
            anomalies_sev = [a for a in audit.anomalies if a.severity == sev]
            if not anomalies_sev:
                continue

            lines.append(f"### {sev} — {len(anomalies_sev)} Issue(s)")
            lines.append("")

            for a in anomalies_sev:
                lines.append(f"#### `[{a.anomaly_type}]` `{a.entity_id}`")
                lines.append("")
                lines.append(f"- **Confidence**: {a.confidence}")
                if a.evidence:
                    lines.append("- **Evidence**:")
                    for ev in a.evidence:
                        lines.append(f"  - {ev}")
                else:
                    lines.append("- **Evidence**: _None_")
                lines.append(f"- **Notes**: {a.notes}")
                lines.append("")

    # Section for Architectural Observations (The Authority Model)
    lines.append("## Architectural Observations")
    lines.append("")
    lines.append(
        "_Entities declared via `runtime_yaml_authority` platforms. "
        "These are functional at runtime but do not appear in the registry by design. "
        "These observations do not impact the `total_anomalies` count._"
    )
    lines.append("")

    if not audit.observations:
        lines.append("No architectural observations.")
        lines.append("")
    else:
        by_obs_type: dict[str, int] = {}
        for o in audit.observations:
            by_obs_type[o.observation_type] = by_obs_type.get(o.observation_type, 0) + 1

        lines.append("| Observation Type | Count |")
        lines.append("|---|---|")
        for obs_type in sorted(by_obs_type.keys()):
            lines.append(f"| `{obs_type}` | {by_obs_type[obs_type]} |")
        lines.append("")

        for obs_type in sorted(by_obs_type.keys()):
            obs_of_type = [o for o in audit.observations if o.observation_type == obs_type]

            lines.append(f"### `{obs_type}` — {len(obs_of_type)} Observation(s)")
            lines.append("")

            for o in obs_of_type:
                lines.append(f"#### `{o.entity_id}`")
                lines.append("")
                lines.append(f"- **Confidence**: {o.confidence}")
                if o.evidence:
                    lines.append("- **Evidence**:")
                    for ev in o.evidence:
                        lines.append(f"  - {ev}")
                else:
                    lines.append("- **Evidence**: _None_")
                lines.append(f"- **Notes**: {o.notes}")
                lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit_engine",
        description=(
            "Architectural Audit Engine for Home Assistant. "
            "Analyzes, classifies, and reports integrity issues without modifying archived versions."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"audit_engine {__version__}",
    )
    parser.add_argument(
        "--ha-root",
        required=True,
        type=Path,
        help="Path to the Home Assistant root directory to audit.",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to the audit_config.yaml file.",
    )
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="Output path for the generated Markdown report.",
    )
    parser.add_argument(
        "--verdict-json",
        required=False,
        type=Path,
        default=None,
        help=(
            "Optional output path for the compact verdict JSON file. "
            "Used by the MQTT publication layer (publish_audit_mqtt.py). "
            "If not provided, no verdict JSON is written."
        ),
    )

    args = parser.parse_args(argv)

    ha_root: Path = args.ha_root.resolve()
    config_path: Path = args.config.resolve()
    report_path: Path = args.report.resolve()
    verdict_json_path: Path | None = args.verdict_json.resolve() if args.verdict_json else None

    _validate_ha_root(ha_root)
    _validate_config(config_path)
    _validate_report_target(report_path)
    if verdict_json_path is not None:
        _validate_report_target(verdict_json_path)

    try:
        from ha_state_archive.audit.include_resolver import resolve_includes
        from ha_state_archive.audit.declaration_extractor import extract_declarations
        from ha_state_archive.audit.reference_extractor import extract_references
        from ha_state_archive.audit.registry_reader import load_registry_entities

        registry_path = ha_root / ".storage" / "core.entity_registry"
        registry_local = load_registry_entities(registry_path, local_only=True)
        registry_all = load_registry_entities(registry_path, local_only=False)

        resolver_result = resolve_includes(ha_root / "configuration.yaml")
        extraction = extract_declarations(resolver_result.files, ha_root)
        ref_result = extract_references(resolver_result.files, ha_root)
        audit_config = _load_audit_config(config_path)

        audit = run_audit(
            registry_local_records=registry_local,
            extraction=extraction,
            registry_all_records=registry_all,
            ref_result=ref_result,
            audit_config=audit_config,
        )

        executed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        report = _render_report(
            audit=audit,
            ha_root=ha_root,
            config_path=config_path,
            executed_at=executed_at,
        )

        try:
            _write_report(report_path, report)
        except OSError as exc:
            _fail(f"Could not write report to {report_path}: {exc}", code=1)

        if verdict_json_path is not None:
            try:
                _write_verdict_json(
                    path=verdict_json_path,
                    audit=audit,
                    ha_root=ha_root,
                    executed_at=executed_at,
                )
                # Backfill report_path into the verdict JSON now that we know it.
                import json as _json
                _vdata = _json.loads(verdict_json_path.read_text(encoding="utf-8"))
                _vdata["report_path"] = str(report_path)
                verdict_json_path.write_text(
                    _json.dumps(_vdata, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError as exc:
                _fail(f"Could not write verdict JSON to {verdict_json_path}: {exc}", code=1)

        # 0  = OK: no actionable anomalies detected.
        # 30 = ALERT: at least one actionable anomaly found (P0-P3).
        exit_code = 30 if len(audit.anomalies) > 0 else 0
        verdict = "ALERT" if exit_code == 30 else "OK"

        print(
            f"audit_engine {__version__} [{verdict}] — "
            f"{len(audit.anomalies)} anomaly(ies), "
            f"{len(audit.observations)} architectural observation(s) — "
            f"report: {report_path}"
        )
        return exit_code

    except SystemExit:
        raise
    except Exception as exc:
        print(f"INTERNAL ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())