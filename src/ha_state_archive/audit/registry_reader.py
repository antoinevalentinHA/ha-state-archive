from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal


LOCAL_PLATFORMS_V1 = {
    "template",
    "statistics",
    "input_boolean",
    "input_text",
    "input_number",
    "input_datetime",
    "input_select",
    "input_button",
    "counter",
    "timer",
    "utility_meter",
}


@dataclass
class EntityRecord:
    entity_id: str
    source: Literal["registry", "declared", "both"]
    platform: str | None
    disabled_by: str | None
    hidden_by: str | None
    file_path: str | None
    line_no: int | None

    domain: str | None = field(default=None)
    unique_id: str | None = field(default=None)
    config_entry_id: str | None = field(default=None)
    original_name: str | None = field(default=None)
    name: str | None = field(default=None)


@dataclass
class RegistrySummary:
    total: int
    by_platform: dict[str, int]
    disabled_count: int
    hidden_count: int


class RegistryReaderError(Exception):
    """Registry reader domain error."""


def _normalize_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return str(value)


def _extract_domain(entity_id: str) -> str | None:
    if "." not in entity_id:
        return None
    domain, _object_id = entity_id.split(".", 1)
    return domain or None


def _is_local_platform(platform: str | None, allowed_platforms: set[str]) -> bool:
    return platform in allowed_platforms


def _has_external_config_entry(raw_entity: dict[str, Any]) -> bool:
    config_entry_id = raw_entity.get("config_entry_id")
    if config_entry_id is None:
        return False
    if isinstance(config_entry_id, str) and not config_entry_id.strip():
        return False
    return True


def _iter_registry_entities(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    entities = payload.get("data", {}).get("entities")
    if not isinstance(entities, list):
        raise RegistryReaderError(
            "Unexpected structure: data.entities key is missing or is not a list."
        )
    for item in entities:
        if isinstance(item, dict):
            yield item


def load_registry_entities(
    registry_path: str | Path,
    allowed_platforms: set[str] | None = None,
    local_only: bool = True,
) -> list[EntityRecord]:
    registry_file = Path(registry_path)

    if not registry_file.exists():
        raise RegistryReaderError(f"File not found: {registry_file}")

    if not registry_file.is_file():
        raise RegistryReaderError(f"Path is not a file: {registry_file}")

    allowed = allowed_platforms or LOCAL_PLATFORMS_V1

    try:
        payload = json.loads(registry_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryReaderError(
            f"Invalid JSON in {registry_file}: {exc}"
        ) from exc
    except OSError as exc:
        raise RegistryReaderError(
            f"Unable to read {registry_file}: {exc}"
        ) from exc

    records: list[EntityRecord] = []

    for raw in _iter_registry_entities(payload):
        entity_id = _normalize_optional_str(raw.get("entity_id"))
        if not entity_id:
            continue

        platform = _normalize_optional_str(raw.get("platform"))
        domain = _extract_domain(entity_id)
        unique_id = _normalize_optional_str(raw.get("unique_id"))
        config_entry_id = _normalize_optional_str(raw.get("config_entry_id"))
        disabled_by = _normalize_optional_str(raw.get("disabled_by"))
        hidden_by = _normalize_optional_str(raw.get("hidden_by"))
        original_name = _normalize_optional_str(raw.get("original_name"))
        name = _normalize_optional_str(raw.get("name"))

        if local_only:
            if not _is_local_platform(platform, allowed):
                continue
            if _has_external_config_entry(raw):
                continue

        records.append(
            EntityRecord(
                entity_id=entity_id,
                source="registry",
                platform=platform,
                disabled_by=disabled_by,
                hidden_by=hidden_by,
                file_path=None,
                line_no=None,
                domain=domain,
                unique_id=unique_id,
                config_entry_id=config_entry_id,
                original_name=original_name,
                name=name,
            )
        )

    records.sort(key=lambda r: r.entity_id)
    return records


def build_registry_index(records: list[EntityRecord]) -> dict[str, EntityRecord]:
    index: dict[str, EntityRecord] = {}
    for record in records:
        if record.entity_id in index:
            warnings.warn(
                f"duplicated entity_id detected in registry: {record.entity_id}",
                stacklevel=2,
            )
        index[record.entity_id] = record
    return index


def summarize_registry(records: list[EntityRecord]) -> RegistrySummary:
    by_platform: dict[str, int] = {}
    disabled_count = 0
    hidden_count = 0

    for record in records:
        key = record.platform or "<none>"
        by_platform[key] = by_platform.get(key, 0) + 1

        if record.disabled_by is not None:
            disabled_count += 1
        if record.hidden_by is not None:
            hidden_count += 1

    return RegistrySummary(
        total=len(records),
        by_platform=dict(sorted(by_platform.items())),
        disabled_count=disabled_count,
        hidden_count=hidden_count,
    )
