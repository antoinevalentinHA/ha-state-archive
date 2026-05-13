from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

_SCOPED_DIRS = {
    "10_scripts",
    "11_automations",
    "12_template_sensors",
    "13_sensor_platforms",
}

RefType = Literal["structured", "jinja_simple", "jinja_dynamic"]
ContextType = Literal["automation", "script", "template", "sensor_platform", "other"]


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@dataclass
class EntityReference:
    entity_id: str
    ref_type: RefType
    context_type: ContextType
    file_path: Path
    line_no: int | None
    raw_snippet: str


@dataclass
class ReferenceResult:
    references: list[EntityReference] = field(default_factory=list)
    dynamic_refs: list[EntityReference] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)


@dataclass
class ReferenceSummary:
    total_static: int
    total_dynamic: int
    unique_entity_ids: int
    by_context: dict[str, int]
    by_ref_type: dict[str, int]
    skipped_files: int
    parse_errors: int


# ---------------------------------------------------------------------------
# Jinja patterns
# ---------------------------------------------------------------------------

_JINJA_SIMPLE_FUNCS = r"(?:states|is_state|state_attr|has_value|is_state_attr)"

_JINJA_SIMPLE_RE = re.compile(
    r"\b" + _JINJA_SIMPLE_FUNCS +
    r"""\s*\(\s*['"]([a-z_]+\.[a-zA-Z0-9_]+)['"]""",
)

_JINJA_DYNAMIC_RE = re.compile(
    r"\b" + _JINJA_SIMPLE_FUNCS +
    r"""\s*\(\s*(?!['"][a-z_]+\.[a-zA-Z0-9_]+['"])""",
)

_JINJA_EXPAND_RE = re.compile(
    r"\b(?:expand|area_entities|device_entities)\s*\(",
)

_ENTITY_ID_RE = re.compile(r"^[a-z_]+\.[a-zA-Z0-9_]+$")

# Structured YAML keys that carry entity_id values.
# "to" / "from" intentionally excluded:
# they represent states, not entity references.
_STRUCTURED_KEYS = {"entity_id", "entity", "entities"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_valid_entity_id(value: str) -> bool:
    return bool(_ENTITY_ID_RE.match(value))


def _infer_context(file_path: Path, ha_root: Path) -> ContextType:
    try:
        rel = file_path.relative_to(ha_root)
    except ValueError:
        return "other"
    first = rel.parts[0] if rel.parts else ""
    mapping: dict[str, ContextType] = {
        "10_scripts": "script",
        "11_automations": "automation",
        "12_template_sensors": "template",
        "13_sensor_platforms": "sensor_platform",
    }
    return mapping.get(first, "other")


def _in_scope(file_path: Path, ha_root: Path) -> bool:
    try:
        rel = file_path.relative_to(ha_root)
    except ValueError:
        return False
    return rel.parts[0] in _SCOPED_DIRS if rel.parts else False


# ---------------------------------------------------------------------------
# Permissive YAML loader
# ---------------------------------------------------------------------------

def _load_yaml_permissive(content: str, file_path: Path) -> tuple[object, str | None]:
    class _Loader(yaml.SafeLoader):
        pass

    def _passthrough_multi(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> object:
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return None

    _Loader.add_multi_constructor("!", _passthrough_multi)

    try:
        return yaml.load(content, Loader=_Loader), None
    except yaml.YAMLError as exc:
        return None, f"{file_path}: {exc}"


# ---------------------------------------------------------------------------
# Structured YAML extraction
# ---------------------------------------------------------------------------

def _collect_entity_values(
    value: object,
    context: ContextType,
    file_path: Path,
    result: ReferenceResult,
) -> None:
    def _append(eid: str) -> None:
        result.references.append(EntityReference(
            entity_id=eid,
            ref_type="structured",
            context_type=context,
            file_path=file_path,
            line_no=None,
            raw_snippet=eid,
        ))

    if isinstance(value, str):
        candidate = value.strip()
        if _is_valid_entity_id(candidate):
            _append(candidate)
        else:
            # CSV fallback (rare but observed in real HA configurations)
            for part in (p.strip() for p in candidate.split(",")):
                if _is_valid_entity_id(part):
                    _append(part)

    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                candidate = item.strip()
                if _is_valid_entity_id(candidate):
                    _append(candidate)


def _extract_structured(
    node: object,
    context: ContextType,
    file_path: Path,
    result: ReferenceResult,
    _depth: int = 0,
) -> None:
    if _depth > 40:
        return

    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                continue
            if key in _STRUCTURED_KEYS:
                _collect_entity_values(value, context, file_path, result)
            else:
                _extract_structured(value, context, file_path, result, _depth + 1)

    elif isinstance(node, list):
        for item in node:
            _extract_structured(item, context, file_path, result, _depth + 1)


# ---------------------------------------------------------------------------
# Jinja extraction
# ---------------------------------------------------------------------------

def _extract_jinja(
    content: str,
    context: ContextType,
    file_path: Path,
    result: ReferenceResult,
) -> None:
    for line_no, line in enumerate(content.splitlines(), start=1):
        seen_on_line: set[str] = set()

        for match in _JINJA_SIMPLE_RE.finditer(line):
            eid = match.group(1)
            if not _is_valid_entity_id(eid):
                continue

            if eid.endswith("_"):
                key = f"<prefix:{eid}>"
                if key not in seen_on_line:
                    seen_on_line.add(key)
                    result.dynamic_refs.append(EntityReference(
                        entity_id=key,
                        ref_type="jinja_dynamic",
                        context_type=context,
                        file_path=file_path,
                        line_no=line_no,
                        raw_snippet=line.strip()[:120],
                    ))
            else:
                result.references.append(EntityReference(
                    entity_id=eid,
                    ref_type="jinja_simple",
                    context_type=context,
                    file_path=file_path,
                    line_no=line_no,
                    raw_snippet=line.strip()[:120],
                ))

        has_simple = bool(_JINJA_SIMPLE_RE.search(line))

        if not has_simple and _JINJA_DYNAMIC_RE.search(line):
            result.dynamic_refs.append(EntityReference(
                entity_id="<dynamic>",
                ref_type="jinja_dynamic",
                context_type=context,
                file_path=file_path,
                line_no=line_no,
                raw_snippet=line.strip()[:120],
            ))

        if _JINJA_EXPAND_RE.search(line):
            result.dynamic_refs.append(EntityReference(
                entity_id="<expand_or_area>",
                ref_type="jinja_dynamic",
                context_type=context,
                file_path=file_path,
                line_no=line_no,
                raw_snippet=line.strip()[:120],
            ))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def extract_references(
    resolved_files: list,
    ha_root: Path,
) -> ReferenceResult:
    result = ReferenceResult()

    for resolved_file in resolved_files:
        file_path: Path = resolved_file.path
        content: str = resolved_file.content

        if not _in_scope(file_path, ha_root):
            result.skipped_files.append(str(file_path))
            continue

        context = _infer_context(file_path, ha_root)

        # Jinja extraction on raw content
        _extract_jinja(content, context, file_path, result)

        # Structured extraction on parsed document
        data, error = _load_yaml_permissive(content, file_path)
        if error:
            result.parse_errors.append(error)
            continue
        if data is not None:
            _extract_structured(data, context, file_path, result)

    return result


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize_references(result: ReferenceResult) -> ReferenceSummary:
    by_context: dict[str, int] = {}
    by_ref_type: dict[str, int] = {}
    unique_ids: set[str] = set()

    for ref in result.references:
        by_context[ref.context_type] = by_context.get(ref.context_type, 0) + 1
        by_ref_type[ref.ref_type] = by_ref_type.get(ref.ref_type, 0) + 1
        unique_ids.add(ref.entity_id)

    return ReferenceSummary(
        total_static=len(result.references),
        total_dynamic=len(result.dynamic_refs),
        unique_entity_ids=len(unique_ids),
        by_context=dict(sorted(by_context.items())),
        by_ref_type=dict(sorted(by_ref_type.items())),
        skipped_files=len(result.skipped_files),
        parse_errors=len(result.parse_errors),
    )
