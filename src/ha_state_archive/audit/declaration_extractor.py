from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import re
import unicodedata
import yaml


DECLARATIVE_DOMAINS_HIGH = {
    "input_boolean",
    "input_text",
    "input_number",
    "input_datetime",
    "input_select",
    "counter",
    "timer",
    "utility_meter",
    "group",
    "manual_alarm_panel",
    "history_stats",
    "zone",
}

DECLARATIVE_DOMAINS_PARTIAL = {
    "template",
    "statistics",
}


# ---------------------------------------------------------------------------
# Authority classification
# ---------------------------------------------------------------------------

REGISTRY_AUTHORITY = "registry_authority"
RUNTIME_YAML_AUTHORITY = "runtime_yaml_authority"

# Contractual authority mapping.
# Any platform absent from this table defaults to registry_authority.
PLATFORM_AUTHORITY_CLASS: dict[str, str] = {
    "group": RUNTIME_YAML_AUTHORITY,
    "utility_meter": RUNTIME_YAML_AUTHORITY,
    "statistics": RUNTIME_YAML_AUTHORITY,
    "history_stats": RUNTIME_YAML_AUTHORITY,
    "manual_alarm_panel": RUNTIME_YAML_AUTHORITY,
    "zone": RUNTIME_YAML_AUTHORITY,
}


def _authority_class_for(platform: str) -> str:
    """Resolve the authority class of a platform.
    Implicit default: registry_authority."""
    return PLATFORM_AUTHORITY_CLASS.get(platform, REGISTRY_AUTHORITY)


def _validate_authority_class_table() -> None:
    """Defensive guard: the authority table must match the declared set.
    Executed on every call to extract_declarations() to prevent any
    silent drift in the runtime_yaml_authority platform set."""
    expected = {
        "group",
        "utility_meter",
        "statistics",
        "history_stats",
        "manual_alarm_panel",
        "zone",
    }

    actual = set(PLATFORM_AUTHORITY_CLASS)

    if actual != expected:
        raise AssertionError(
            "PLATFORM_AUTHORITY_CLASS does not match the expected set "
            f"(expected={sorted(expected)}, actual={sorted(actual)})"
        )


@dataclass
class DeclaredEntity:
    entity_id: str | None
    domain: str | None
    platform: str
    file_path: Path
    raw_name: str | None
    raw_unique_id: str | None
    confidence: str              # "high" | "partial"
    derivation: str             # "direct_key" | "derived_from_name" | "structural"
    authority_class: str = field(init=False)  # Derived from platform

    def __post_init__(self) -> None:
        if not self.platform:
            raise ValueError(
                "DeclaredEntity: platform is required to resolve authority_class"
            )

        self.authority_class = _authority_class_for(self.platform)


@dataclass
class ExtractionResult:
    entities: list[DeclaredEntity] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)


@dataclass
class ExtractionSummary:
    total: int
    high_confidence: int
    partial_confidence: int
    by_platform: dict[str, int]
    parse_errors: int
    skipped_files: int


# ---------------------------------------------------------------------------
# YAML
# ---------------------------------------------------------------------------

class _AuditLoader(yaml.SafeLoader):
    pass


def _construct_passthrough(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


_AuditLoader.add_constructor("!secret", _construct_passthrough)


def _safe_load(content: str, file_path: Path) -> tuple[Any, str | None]:
    try:
        return yaml.load(content, Loader=_AuditLoader), None
    except yaml.YAMLError as exc:
        return None, f"{file_path}: {exc}"


# ---------------------------------------------------------------------------
# Home Assistant compatible slugify
# ---------------------------------------------------------------------------

_SLUGIFY_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SLUGIFY_RE_MULTI_UNDERSCORE = re.compile(r"_+")


def _ha_slugify(value: str) -> str:
    """
    Local pragmatic reproduction of the Home Assistant slugify.

    Invariants:
    - lowercase
    - strip Unicode accents
    - non-alphanumeric separators -> "_"
    - collapse repeated "_"
    - trim leading/trailing "_"

    The engine does not silently repair input.
    Any observed divergence from real HA behaviour must be
    fixed explicitly in this function.
    """
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()

    slug = _SLUGIFY_RE_NON_ALNUM.sub("_", lowered)
    slug = _SLUGIFY_RE_MULTI_UNDERSCORE.sub("_", slug)

    return slug.strip("_")


_SLUGIFY_TEST_CASES = [
    ("Alarme Maison", "alarme_maison"),
    ("Durée aération Étage", "duree_aeration_etage"),
    ("CPU médiane 7 j Core", "cpu_mediane_7_j_core"),
    ("deltaT chambre Arnaud", "deltat_chambre_arnaud"),
    ("Température extérieure", "temperature_exterieure"),
]


def _validate_slugify() -> None:
    """
    Minimal behavioural validation of _ha_slugify().
    Fails immediately on any divergence.
    """
    for raw, expected in _SLUGIFY_TEST_CASES:
        actual = _ha_slugify(raw)

        if actual != expected:
            raise RuntimeError(
                f"_ha_slugify divergence: "
                f"{raw!r} -> {actual!r} (expected {expected!r})"
            )


def _derive_entity_id_from_name(
    domain: str,
    raw_name: str | None,
) -> str | None:
    """
    Canonical entity_id reconstruction:
    entity_id = <domain>.<slugify(name)>
    """
    if raw_name is None:
        return None

    slug = _ha_slugify(raw_name)

    if not slug:
        return None

    return f"{domain}.{slug}"


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------

def _extract_named_dict(
    data: dict[str, Any],
    domain: str,
    file_path: Path,
    result: ExtractionResult,
) -> None:
    """
    !include_dir_merge_named domains: input_*, counter, timer.
    Expected structure: {object_id: {name: ..., ...}, ...}
    entity_id = domain.object_id — high confidence.
    """
    for object_id, body in data.items():
        if not isinstance(object_id, str) or not object_id.strip():
            continue

        raw_name = None
        if isinstance(body, dict):
            name = body.get("name")
            if isinstance(name, str) and name.strip():
                raw_name = name.strip()

        result.entities.append(DeclaredEntity(
            entity_id=f"{domain}.{object_id}",
            domain=domain,
            platform=domain,
            file_path=file_path,
            raw_name=raw_name,
            raw_unique_id=None,
            confidence="high",
            derivation="direct_key",
        ))


def _extract_utility_meter(
    data: Any,
    file_path: Path,
    result: ExtractionResult,
) -> None:
    """
    utility_meter.yaml: dict {object_id: {source: ..., cycle: ..., name: ...}}

    - if name is present: entity_id = sensor.<slugify(name)>
    - otherwise:          entity_id = sensor.<object_id>
    """
    if not isinstance(data, dict):
        return

    for object_id, body in data.items():
        if not isinstance(object_id, str) or not object_id.strip():
            continue

        raw_name = None
        entity_id = f"sensor.{object_id}"
        derivation = "direct_key"

        if isinstance(body, dict):
            name = body.get("name")
            if isinstance(name, str) and name.strip():
                raw_name = name.strip()
                derived_entity_id = _derive_entity_id_from_name(
                    "sensor",
                    raw_name,
                )

                if derived_entity_id is not None:
                    entity_id = derived_entity_id
                    derivation = "derived_from_name"

        result.entities.append(DeclaredEntity(
            entity_id=entity_id,
            domain="sensor",
            platform="utility_meter",
            file_path=file_path,
            raw_name=raw_name,
            raw_unique_id=None,
            confidence="high",
            derivation=derivation,
        ))


def _extract_template_block(
    data: Any,
    file_path: Path,
    result: ExtractionResult,
) -> None:
    """
    Modern template platform: list of dicts with sensor: / binary_sensor: keys.
    trigger: ignored — it is a trigger, not an entity.
    No entity_id reconstruction — partial confidence.
    """
    blocks = data if isinstance(data, list) else [data]

    for block in blocks:
        if not isinstance(block, dict):
            continue

        for key in ("sensor", "binary_sensor"):
            entities = block.get(key)
            if not entities:
                continue

            items = entities if isinstance(entities, list) else [entities]
            for item in items:
                if not isinstance(item, dict):
                    continue

                name = item.get("name")
                unique_id = item.get("unique_id")

                result.entities.append(DeclaredEntity(
                    entity_id=None,
                    domain=key,
                    platform="template",
                    file_path=file_path,
                    raw_name=name if isinstance(name, str) else None,
                    raw_unique_id=unique_id if isinstance(unique_id, str) else None,
                    confidence="partial",
                    derivation="structural",
                ))


def _extract_statistics(
    data: Any,
    file_path: Path,
    result: ExtractionResult,
) -> None:
    """
    Legacy statistics platform.

    Canonical entity_id reconstruction:
    sensor.<slugify(name)>
    """
    items = data if isinstance(data, list) else [data]

    for item in items:
        if not isinstance(item, dict):
            continue

        platform = item.get("platform")

        if platform != "statistics":
            continue

        name = item.get("name")
        unique_id = item.get("unique_id")

        if not isinstance(name, str):
            continue

        entity_id = _derive_entity_id_from_name(
            "sensor",
            name,
        )

        if entity_id is None:
            continue

        result.entities.append(DeclaredEntity(
            entity_id=entity_id,
            domain="sensor",
            platform="statistics",
            file_path=file_path,
            raw_name=name,
            raw_unique_id=(
                unique_id
                if isinstance(unique_id, str)
                else None
            ),
            confidence="high",
            derivation="derived_from_name",
        ))


def _extract_groups(
    data: Any,
    file_path: Path,
    result: ExtractionResult,
) -> None:
    """
    Group entities declared through YAML object IDs.
    object_id = YAML key.
    Direct reconstruction: group.<object_id>.
    """
    if not isinstance(data, dict):
        return

    for object_id in data.keys():
        if not isinstance(object_id, str):
            continue

        object_id = object_id.strip()

        if not object_id:
            continue

        result.entities.append(DeclaredEntity(
            entity_id=f"group.{object_id}",
            domain="group",
            platform="group",
            file_path=file_path,
            raw_name=object_id,
            raw_unique_id=None,
            confidence="high",
            derivation="direct_key",
        ))


def _extract_manual_alarm_control_panel(
    data: Any,
    file_path: Path,
    result: ExtractionResult,
) -> None:
    """
    Legacy alarm_control_panel list platform.
    entity_id derived from name via _ha_slugify().
    """
    items = data if isinstance(data, list) else [data]

    for item in items:
        if not isinstance(item, dict):
            continue

        platform = item.get("platform")
        name = item.get("name")

        if platform != "manual":
            continue

        if not isinstance(name, str):
            continue

        entity_id = _derive_entity_id_from_name(
            "alarm_control_panel",
            name,
        )

        if entity_id is None:
            continue

        result.entities.append(DeclaredEntity(
            entity_id=entity_id,
            domain="alarm_control_panel",
            platform="manual_alarm_panel",
            file_path=file_path,
            raw_name=name,
            raw_unique_id=None,
            confidence="high",
            derivation="derived_from_name",
        ))


def _extract_history_stats(
    data: Any,
    file_path: Path,
    result: ExtractionResult,
) -> None:
    """
    Legacy history_stats platform.
    entity_id derived from name via _ha_slugify().
    """
    items = data if isinstance(data, list) else [data]

    for item in items:
        if not isinstance(item, dict):
            continue

        platform = item.get("platform")
        name = item.get("name")

        if platform != "history_stats":
            continue

        if not isinstance(name, str):
            continue

        entity_id = _derive_entity_id_from_name(
            "sensor",
            name,
        )

        if entity_id is None:
            continue

        result.entities.append(DeclaredEntity(
            entity_id=entity_id,
            domain="sensor",
            platform="history_stats",
            file_path=file_path,
            raw_name=name,
            raw_unique_id=None,
            confidence="high",
            derivation="derived_from_name",
        ))


def _extract_zones(
    data: Any,
    file_path: Path,
    result: ExtractionResult,
) -> None:
    """
    Home Assistant zones declared in YAML.
    entity_id derived from name via _ha_slugify().
    """
    items = data if isinstance(data, list) else [data]

    for item in items:
        if not isinstance(item, dict):
            continue

        name = item.get("name")

        if not isinstance(name, str):
            continue

        entity_id = _derive_entity_id_from_name(
            "zone",
            name,
        )

        if entity_id is None:
            continue

        result.entities.append(DeclaredEntity(
            entity_id=entity_id,
            domain="zone",
            platform="zone",
            file_path=file_path,
            raw_name=name,
            raw_unique_id=None,
            confidence="high",
            derivation="derived_from_name",
        ))


# ---------------------------------------------------------------------------
# Domain inference from path
# ---------------------------------------------------------------------------

_PATH_DOMAIN_MAP: dict[str, str] = {
    "02_groups": "group",
    "03_input_numbers": "input_number",
    "04_input_texts": "input_text",
    "05_input_booleans": "input_boolean",
    "06_input_selects": "input_select",
    "07_input_datetimes": "input_datetime",
    "08_timers": "timer",
    "09_counters": "counter",
    "12_template_sensors": "template",
    "13_sensor_platforms": "history_stats",
    "16_template_alarm_panels": "manual_alarm_panel",
    "17_zones": "zone",
}


def _infer_domain(file_path: Path, root: Path) -> str | None:
    try:
        rel = file_path.relative_to(root)
    except ValueError:
        return None

    if rel.name == "utility_meter.yaml":
        return "utility_meter"

    first = rel.parts[0] if rel.parts else ""
    return _PATH_DOMAIN_MAP.get(first)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def extract_declarations(
    resolved_files: list,
    ha_root: Path,
) -> ExtractionResult:
    result = ExtractionResult()
    _validate_slugify()
    _validate_authority_class_table()

    for resolved_file in resolved_files:
        file_path: Path = resolved_file.path
        content: str = resolved_file.content

        domain = _infer_domain(file_path, ha_root)
        if domain is None:
            result.skipped_files.append(str(file_path))
            continue

        data, error = _safe_load(content, file_path)
        if error is not None:
            result.parse_errors.append(error)
            continue
        if data is None:
            result.skipped_files.append(str(file_path))
            continue

        if domain in DECLARATIVE_DOMAINS_PARTIAL:
            if domain == "template":
                _extract_template_block(data, file_path, result)

        elif domain in DECLARATIVE_DOMAINS_HIGH:
            if domain == "utility_meter":
                _extract_utility_meter(data, file_path, result)

            elif domain == "group":
                _extract_groups(data, file_path, result)

            elif domain == "manual_alarm_panel":
                _extract_manual_alarm_control_panel(
                    data,
                    file_path,
                    result,
                )

            elif domain == "history_stats":
                _extract_history_stats(
                    data,
                    file_path,
                    result,
                )

                # statistics entities may coexist in the same directory
                _extract_statistics(
                    data,
                    file_path,
                    result,
                )

            elif domain == "zone":
                _extract_zones(
                    data,
                    file_path,
                    result,
                )

            elif isinstance(data, dict):
                _extract_named_dict(
                    data,
                    domain,
                    file_path,
                    result,
                )

    result.entities.sort(key=lambda e: (e.entity_id or "", e.platform))
    return result


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize_extraction(result: ExtractionResult) -> ExtractionSummary:
    by_platform: dict[str, int] = {}
    high = 0
    partial = 0

    for e in result.entities:
        by_platform[e.platform] = by_platform.get(e.platform, 0) + 1
        if e.confidence == "high":
            high += 1
        else:
            partial += 1

    return ExtractionSummary(
        total=len(result.entities),
        high_confidence=high,
        partial_confidence=partial,
        by_platform=dict(sorted(by_platform.items())),
        parse_errors=len(result.parse_errors),
        skipped_files=len(result.skipped_files),
    )