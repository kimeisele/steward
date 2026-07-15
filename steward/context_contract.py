"""Pure semantic contract for the Context Bridge.

This module has no filesystem, network, clock, Git, service-registry, or writer
integration. Callers must provide every input explicitly.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_C0_BYTES = 4_096
MAX_SOURCE_BYTES = 32_768

C0_BEGIN = "<!-- steward-context:c0:v1:begin -->"
C0_END = "<!-- steward-context:c0:v1:end -->"
ORIENTATION_BEGIN = "<!-- steward-context:orientation:v1:begin -->"
ORIENTATION_END = "<!-- steward-context:orientation:v1:end -->"

_KNOWN_MARKERS = (C0_BEGIN, C0_END, ORIENTATION_BEGIN, ORIENTATION_END)
_PARTICIPATING_SOURCES = (
    "campaign",
    "cetana",
    "constitution",
    "context_schema",
    "federation",
    "gaps",
    "health",
    "immune",
    "orientation",
    "repository",
    "senses",
)
_ALL_SOURCES = frozenset(
    {
        "annotations",
        "architecture",
        "campaign",
        "cetana",
        "constitution",
        "context_schema",
        "continuity",
        "federation",
        "gaps",
        "health",
        "immune",
        "issues",
        "orientation",
        "repository",
        "senses",
        "sessions",
        "tasks",
    }
)
_GAP_CATEGORIES = frozenset({"knowledge", "provider", "skill", "tool"})
_CAMPAIGN_KINDS = frozenset({"active_missions_at_most", "ci_green", "federation_healthy", "immune_clean"})
_SENSE_IDS = frozenset({"caksu", "ghrana", "jihva", "srotra", "tvak"})
_SENSE_QUALITIES = frozenset({"sattva", "rajas", "tamas", "unknown"})
_FEDERATION_STATUSES = frozenset({"alive", "suspect", "dead", "evicted"})
_SOURCE_MODES = frozenset({"live", "cached", "static", "derived"})
_AGE_BUCKETS = frozenset({"fresh", "stale", "unknown"})
_ERROR_CODES = frozenset(
    {
        "missing",
        "read_failed",
        "invalid_utf8",
        "invalid_markers",
        "invalid_schema",
        "invalid_type",
        "invalid_value",
        "inconsistent",
        "unsafe_content",
        "unsupported_version",
        "stale_cache",
        "provenance_missing",
    }
)
_SOURCE_TRUST = {
    "annotations": "t3_advisory_project",
    "architecture": "t1_verified_evidence",
    "campaign": "t2_validated_operational",
    "cetana": "t2_validated_operational",
    "constitution": "t0_constitution",
    "context_schema": "t1_verified_evidence",
    "continuity": "t3_advisory_project",
    "federation": "t2_validated_operational",
    "gaps": "t2_validated_operational",
    "health": "t2_validated_operational",
    "immune": "t2_validated_operational",
    "issues": "t4_external_untrusted",
    "orientation": "t1_verified_evidence",
    "repository": "t1_verified_evidence",
    "senses": "t2_validated_operational",
    "sessions": "t3_advisory_project",
    "tasks": "t3_advisory_project",
}
_SOURCE_MODE = {
    "annotations": "derived",
    "architecture": "derived",
    "campaign": "live",
    "cetana": "live",
    "constitution": "static",
    "context_schema": "derived",
    "continuity": "static",
    "federation": "live",
    "gaps": "live",
    "health": "live",
    "immune": "live",
    "issues": "live",
    "orientation": "static",
    "repository": "derived",
    "senses": "live",
    "sessions": "live",
    "tasks": "live",
}
_REPOSITORY_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ASCII_ID = re.compile(r"^[a-z0-9][a-z0-9_./-]{0,127}$")
_JSON_KEY = re.compile(r"^[A-Za-z0-9_.-]+$")
_BIDI_OR_ZERO_WIDTH = frozenset(
    {
        "\u200b",
        "\u200c",
        "\u200d",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\ufeff",
    }
)


class SourceStatus(str, Enum):
    VALID = "valid"
    EMPTY = "empty"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    STALE = "stale"
    UNSAFE = "unsafe"
    UNSUPPORTED = "unsupported"


class TrustZone(str, Enum):
    T0_CONSTITUTION = "t0_constitution"
    T1_VERIFIED_EVIDENCE = "t1_verified_evidence"
    T2_VALIDATED_OPERATIONAL = "t2_validated_operational"
    T3_ADVISORY_PROJECT = "t3_advisory_project"
    T4_EXTERNAL_UNTRUSTED = "t4_external_untrusted"
    T5_GENERATIVE = "t5_generative"


class OutputMode(str, Enum):
    CANONICAL = "canonical"
    DEGRADED = "degraded"
    SAFE_FALLBACK = "safe_fallback"
    PREVIEW = "preview"


class Decision(str, Enum):
    PUBLISH = "publish"
    NO_OP = "no_op"
    MANUAL_REVIEW = "manual_review"
    BLOCKED = "blocked"


class ContractViolation(ValueError):
    """Structured contract error that never echoes the rejected raw value."""

    def __init__(self, code: str, *, field_path: str = "", source_id: str = "") -> None:
        self.code = code
        self.field_path = field_path
        self.source_id = source_id
        location = field_path or "contract"
        source = f" source={source_id}" if source_id else ""
        super().__init__(f"context contract violation: {code} at {location}{source}")


@dataclass(frozen=True)
class ParsedConventions:
    c0: str
    orientation: str | None
    c0_version: str = "c0/v1"
    orientation_version: str | None = "orientation/v1"


@dataclass(frozen=True)
class SourceResult:
    source_id: str
    trust_zone: TrustZone
    status: SourceStatus
    source_mode: str
    observed_at: str | None
    age_bucket: str
    schema_version: str | None
    value: object | None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or self.source_id not in _ALL_SOURCES:
            raise ContractViolation("unsupported_version", field_path="source_id")
        if not isinstance(self.trust_zone, TrustZone) or not isinstance(self.status, SourceStatus):
            raise ContractViolation("invalid_type", field_path=f"sources.{self.source_id}")
        if self.trust_zone.value != _SOURCE_TRUST[self.source_id]:
            raise ContractViolation("inconsistent", field_path=f"sources.{self.source_id}.trust_zone")
        if self.source_mode not in _SOURCE_MODES:
            raise ContractViolation("invalid_value", field_path=f"sources.{self.source_id}.source_mode")
        if self.source_mode != _SOURCE_MODE[self.source_id]:
            raise ContractViolation("inconsistent", field_path=f"sources.{self.source_id}.source_mode")
        if self.age_bucket not in _AGE_BUCKETS:
            raise ContractViolation("unsupported_version", field_path=f"sources.{self.source_id}.age_bucket")
        if self.source_mode == "cached" and self.age_bucket != "stale":
            raise ContractViolation("inconsistent", field_path=f"sources.{self.source_id}.age_bucket")
        successful = self.status in {SourceStatus.VALID, SourceStatus.EMPTY}
        if self.value is not None and not successful and self.status is not SourceStatus.STALE:
            raise ContractViolation("inconsistent", field_path=f"sources.{self.source_id}.value")
        if successful and self.source_mode in {"live", "derived"}:
            _validate_timestamp(self.observed_at, field_path=f"sources.{self.source_id}.observed_at")
        if self.schema_version is not None:
            _validate_ascii_identifier(self.schema_version, field_path=f"sources.{self.source_id}.schema_version")
        if self.error_code is not None and self.error_code not in _ERROR_CODES:
            raise ContractViolation("unsupported_version", field_path=f"sources.{self.source_id}.error_code")
        object.__setattr__(self, "value", _freeze(self.value))


@dataclass(frozen=True)
class ConstitutionAttestation:
    c0_sha256: str
    source_blob: str
    reviewed_at_commit: str
    schema: str = "steward.context.constitution-attestation/v1"
    status: str = "verified"


@dataclass(frozen=True)
class PreviousPublishedRecord:
    payload_hash: str
    snapshot_id: str
    c0_sha256: str
    mode: OutputMode
    consumer_outputs: Mapping[str, str]
    comparison_state: Mapping[str, int | None]
    record_schema: str = "steward.context.published-record/v1"
    payload_schema: str = "steward.context.payload/v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "consumer_outputs", MappingProxyType(dict(self.consumer_outputs)))
        object.__setattr__(self, "comparison_state", MappingProxyType(dict(self.comparison_state)))


@dataclass(frozen=True)
class ContractDecision:
    decision: Decision
    reason: str


def _fail(code: str, field_path: str = "", source_id: str = "") -> None:
    raise ContractViolation(code, field_path=field_path, source_id=source_id)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            _fail("invalid_type", "source.value")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _normalize_unicode(value: str, *, field_path: str, allow_lf: bool) -> str:
    if not isinstance(value, str):
        _fail("invalid_type", field_path)
    normalized = unicodedata.normalize("NFC", value)
    for character in normalized:
        codepoint = ord(character)
        if character in _BIDI_OR_ZERO_WIDTH or character in {"\u2028", "\u2029"}:
            _fail("invalid_value", field_path)
        if codepoint < 32 or 127 <= codepoint <= 159:
            if allow_lf and character == "\n":
                continue
            _fail("invalid_value", field_path)
    return normalized


def _validate_ascii_identifier(value: str, *, field_path: str) -> str:
    value = _normalize_unicode(value, field_path=field_path, allow_lf=False)
    if not _ASCII_ID.fullmatch(value):
        _fail("invalid_value", field_path)
    return value


def _validate_timestamp(value: str | None, *, field_path: str) -> str:
    if not isinstance(value, str) or not _RFC3339_UTC.fullmatch(value):
        _fail("invalid_value", field_path)
    return value


def _validate_hash(value: str, length: int, *, field_path: str) -> str:
    pattern = _HEX40 if length == 40 else _HEX64
    if not isinstance(value, str) or not pattern.fullmatch(value):
        _fail("invalid_value", field_path)
    return value


def _count(value: object, *, field_path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("invalid_type", field_path)
    if value < 0 or value > MAX_SAFE_INTEGER:
        _fail("invalid_value", field_path)
    return value


def _unit_number(value: object, *, field_path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("invalid_type", field_path)
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0 or numeric > 1:
        _fail("invalid_value", field_path)
    return numeric


def _reject_unknown_keys(raw: Mapping[str, object], allowed: set[str], *, field_path: str) -> None:
    if set(raw) - allowed:
        _fail("unsupported_version", field_path)


def validate_public_safe_text(value: str, *, field_path: str, multiline: bool = False) -> str:
    """Validate an allowlisted string without returning unsafe diagnostics."""

    normalized = _normalize_unicode(value, field_path=field_path, allow_lf=multiline)
    lowered = normalized.lower()
    if len(normalized.encode("utf-8")) > 4_096:
        _fail("unsafe_content", field_path)
    if any(marker in normalized for marker in _KNOWN_MARKERS) or "<!-- steward-context:" in normalized:
        _fail("unsafe_content", field_path)
    if "-----begin " in lowered and " key-----" in lowered:
        _fail("unsafe_content", field_path)
    if re.search(r"(?i)\b(password|passwd|token|secret|api[_-]?key|credential)\s*[:=]", normalized):
        _fail("unsafe_content", field_path)
    if re.search(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-)", normalized):
        _fail("unsafe_content", field_path)
    if re.search(r"(^|[\s(])/(?!/)", normalized) or re.search(r"(^|[\s(])[A-Za-z]:[\\/]", normalized):
        _fail("unsafe_content", field_path)
    if normalized.startswith("\\\\") or "file://" in lowered:
        _fail("unsafe_content", field_path)
    if re.search(r"(?i)https?://[^/\s]+@", normalized):
        _fail("unsafe_content", field_path)
    if re.search(
        r"(?i)https?://(localhost|127(?:\.\d+){3}|10(?:\.\d+){3}|192\.168(?:\.\d+){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d+){2}|\[::1\])",
        normalized,
    ):
        _fail("unsafe_content", field_path)
    if "ignore previous instructions" in lowered:
        _fail("unsafe_content", field_path)
    if not multiline and ("\n" in normalized or re.search(r"(^|\s)(#|```|<\!--|\[[^]]+\]\()", normalized)):
        _fail("unsafe_content", field_path)
    return normalized


def parse_conventions(source: bytes) -> ParsedConventions:
    """Parse the versioned C0 and optional orientation blocks from explicit bytes."""

    if not isinstance(source, bytes):
        _fail("invalid_type", "conventions")
    if not source:
        _fail("missing", "conventions")
    if len(source) > MAX_SOURCE_BYTES:
        _fail("invalid_value", "conventions")
    if source.startswith(b"\xef\xbb\xbf"):
        _fail("invalid_utf8", "conventions")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        _fail("invalid_utf8", "conventions")
    text = text.replace("\r\n", "\n")
    if "\r" in text or len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        _fail("invalid_value", "conventions")
    text = _normalize_unicode(text, field_path="conventions", allow_lf=True)
    if "<!-- steward-context:dynamic:" in text:
        _fail("invalid_markers", "conventions")
    residual = text
    for marker in _KNOWN_MARKERS:
        if text.count(marker) != (1 if marker in {C0_BEGIN, C0_END} else text.count(marker)):
            _fail("invalid_markers", "conventions")
        residual = residual.replace(marker, "")
    if "<!-- steward-context:" in residual:
        _fail("invalid_markers", "conventions")

    lines = text.split("\n")
    positions: dict[str, list[int]] = {marker: [] for marker in _KNOWN_MARKERS}
    for index, line in enumerate(lines):
        if line in positions:
            positions[line].append(index)
        elif any(marker in line for marker in _KNOWN_MARKERS):
            _fail("invalid_markers", "conventions")
    if len(positions[C0_BEGIN]) != 1 or len(positions[C0_END]) != 1:
        _fail("invalid_markers", "conventions")
    orientation_counts = (len(positions[ORIENTATION_BEGIN]), len(positions[ORIENTATION_END]))
    if orientation_counts not in {(0, 0), (1, 1)}:
        _fail("invalid_markers", "conventions")

    c0_start = positions[C0_BEGIN][0]
    c0_end = positions[C0_END][0]
    if c0_start >= c0_end:
        _fail("invalid_markers", "conventions")
    orientation_present = orientation_counts == (1, 1)
    orientation_start = positions[ORIENTATION_BEGIN][0] if orientation_present else None
    orientation_end = positions[ORIENTATION_END][0] if orientation_present else None
    if orientation_present and not (c0_end < orientation_start < orientation_end):
        _fail("invalid_markers", "conventions")

    outside = lines[:c0_start]
    outside += lines[c0_end + 1 : orientation_start if orientation_start is not None else len(lines)]
    if orientation_end is not None:
        outside += lines[orientation_end + 1 :]
    if any(line.strip() for line in outside):
        _fail("invalid_markers", "conventions")

    c0 = "\n".join(lines[c0_start + 1 : c0_end]).rstrip("\n") + "\n"
    if not c0.strip() or len(c0.encode("utf-8")) > MAX_C0_BYTES:
        _fail("invalid_value", "constitution.c0")
    validate_public_safe_text(c0, field_path="constitution.c0", multiline=True)

    orientation: str | None = None
    orientation_version: str | None = None
    if orientation_start is not None and orientation_end is not None:
        orientation = "\n".join(lines[orientation_start + 1 : orientation_end]).rstrip("\n") + "\n"
        if not orientation.strip():
            orientation = ""
        else:
            validate_public_safe_text(orientation, field_path="orientation", multiline=True)
        orientation_version = "orientation/v1"
    return ParsedConventions(c0=c0, orientation=orientation, orientation_version=orientation_version)


def _canonicalize(value: object, *, field_path: str = "$") -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value < 0 or value > MAX_SAFE_INTEGER:
            _fail("invalid_value", field_path)
        return value
    if isinstance(value, float):
        _fail("invalid_type", field_path)
    if isinstance(value, str):
        return _normalize_unicode(value, field_path=field_path, allow_lf=True)
    if isinstance(value, list):
        return [_canonicalize(item, field_path=f"{field_path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not _JSON_KEY.fullmatch(key):
                _fail("invalid_type", field_path)
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                _fail("inconsistent", field_path)
            normalized[normalized_key] = _canonicalize(item, field_path=f"{field_path}.{normalized_key}")
        return normalized
    _fail("invalid_type", field_path)


def canonical_json_bytes(value: object) -> bytes:
    normalized = _canonicalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _domain_hash(domain: str, value: object) -> str:
    return hashlib.sha256(domain.encode("ascii") + b"\0" + canonical_json_bytes(value)).hexdigest()


def snapshot_hash(model: Mapping[str, object]) -> str:
    if model.get("schema") != "steward.context.snapshot/v1":
        _fail("invalid_schema", "snapshot.schema")
    return _domain_hash("steward-context-snapshot-v1", dict(model))


def payload_hash(model: Mapping[str, object]) -> str:
    if model.get("schema") != "steward.context.payload/v1":
        _fail("invalid_schema", "payload.schema")
    return _domain_hash("steward-context-payload-v1", dict(model))


def consumer_output_hash(rendered_bytes: bytes) -> str:
    if not isinstance(rendered_bytes, bytes):
        _fail("invalid_type", "consumer_output")
    return hashlib.sha256(b"steward-context-consumer-output-v1\0" + rendered_bytes).hexdigest()


def normalize_health(raw: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown_keys(
        raw,
        {"value", "guna", "provider_health", "error_pressure", "context_pressure"},
        field_path="health",
    )
    value = _unit_number(raw.get("value"), field_path="health.value")
    provider = _unit_number(raw.get("provider_health"), field_path="health.provider_health")
    guna = raw.get("guna")
    if guna not in {"sattva", "rajas", "tamas"}:
        _fail("unsupported_version", "health.guna")
    expected_guna = "tamas" if value <= 0.3 else "rajas" if value <= 0.7 else "sattva"
    if guna != expected_guna:
        _fail("inconsistent", "health.guna")
    health_class = "critical" if value <= 0.5 else "watch" if value <= 0.8 else "healthy"
    provider_class = "unavailable" if provider == 0 else "healthy" if provider == 1 else "degraded"
    return {"class": health_class, "guna": guna, "provider": provider_class}


def normalize_senses(raw: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown_keys(raw, {"total_pain", "detail", "prompt_summary"}, field_path="senses")
    pain = _unit_number(raw.get("total_pain"), field_path="senses.total_pain")
    pain_class = "clear" if pain < 0.2 else "elevated" if pain <= 0.5 else "high" if pain <= 0.7 else "critical"
    detail = raw.get("detail", {})
    if not isinstance(detail, Mapping):
        _fail("invalid_type", "senses.detail")
    unknown = set(detail) - _SENSE_IDS
    if unknown:
        _fail("unsupported_version", "senses.detail")
    critical_count = 0
    for sense_id, item in detail.items():
        if not isinstance(item, Mapping):
            _fail("invalid_type", f"senses.detail.{sense_id}")
        _reject_unknown_keys(item, {"active", "quality", "pain"}, field_path=f"senses.detail.{sense_id}")
        active = item.get("active")
        quality = item.get("quality")
        if not isinstance(active, bool):
            _fail("invalid_type", f"senses.detail.{sense_id}.active")
        if quality not in _SENSE_QUALITIES:
            _fail("unsupported_version", f"senses.detail.{sense_id}.quality")
        if not active or quality == "tamas":
            critical_count += 1
    return {"pain": pain_class, "critical_count": critical_count}


def normalize_gaps(raw: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown_keys(raw, {"active", "stats", "prompt_summary"}, field_path="gaps")
    active = raw.get("active", [])
    if not isinstance(active, list):
        _fail("invalid_type", "gaps.active")
    categories: set[str] = set()
    for index, gap in enumerate(active):
        if not isinstance(gap, Mapping):
            _fail("invalid_type", f"gaps.active[{index}]")
        _reject_unknown_keys(
            gap,
            {"category", "description", "context", "timestamp", "resolved", "resolution"},
            field_path=f"gaps.active[{index}]",
        )
        category = gap.get("category")
        if category not in _GAP_CATEGORIES:
            _fail("unsupported_version", f"gaps.active[{index}].category")
        categories.add(str(category))
    return {"active_count": _count(len(active), field_path="gaps.active_count"), "categories": sorted(categories)}


def normalize_federation(
    raw: Mapping[str, object], previous_state: Mapping[str, int | None] | None
) -> tuple[dict[str, object], dict[str, int]]:
    _reject_unknown_keys(
        raw,
        {
            "by_status",
            "peers",
            "avg_trust",
            "gateway",
            "marketplace",
            "total_peers",
            "total_reaps",
            "total_evictions",
            "lease_ttl_s",
            "trust_decay",
        },
        field_path="federation",
    )
    by_status = raw.get("by_status", {})
    if not isinstance(by_status, Mapping):
        _fail("invalid_type", "federation.by_status")
    if set(by_status) - _FEDERATION_STATUSES:
        _fail("unsupported_version", "federation.by_status")
    alive = _count(by_status.get("alive", 0), field_path="federation.by_status.alive")
    suspect = _count(by_status.get("suspect", 0), field_path="federation.by_status.suspect")
    dead = _count(by_status.get("dead", 0), field_path="federation.by_status.dead")
    federation_class = "critical" if dead else "degraded" if suspect else "healthy" if alive else "empty"

    gateway = raw.get("gateway", {})
    if not isinstance(gateway, Mapping):
        _fail("invalid_type", "federation.gateway")
    _reject_unknown_keys(
        gateway,
        {"errors", "rejected_parse", "rejected_validate", "total_requests", "by_protocol", "pending_signals"},
        field_path="federation.gateway",
    )
    current = {
        "gateway_errors_total": _count(gateway.get("errors", 0), field_path="federation.gateway.errors"),
        "gateway_rejected_parse_total": _count(
            gateway.get("rejected_parse", 0), field_path="federation.gateway.rejected_parse"
        ),
        "gateway_rejected_validate_total": _count(
            gateway.get("rejected_validate", 0), field_path="federation.gateway.rejected_validate"
        ),
    }
    if previous_state is None:
        gateway_class = "clear" if all(value == 0 for value in current.values()) else "unknown"
    else:
        previous = {key: _count(previous_state.get(key), field_path=f"comparison_state.{key}") for key in current}
        if any(current[key] < previous[key] for key in current):
            _fail("invalid_value", "federation.gateway")
        if current["gateway_errors_total"] > previous["gateway_errors_total"]:
            gateway_class = "error"
        elif any(current[key] > previous[key] for key in current if key != "gateway_errors_total"):
            gateway_class = "degraded"
        else:
            gateway_class = "clear"
    return (
        {"class": federation_class, "alive": alive, "suspect": suspect, "dead": dead, "gateway": gateway_class},
        current,
    )


def normalize_immune(
    raw: Mapping[str, object], previous_state: Mapping[str, int | None] | None
) -> tuple[dict[str, object], dict[str, int]]:
    _reject_unknown_keys(
        raw,
        {"available", "breaker", "heals_attempted", "heals_succeeded", "heals_rolled_back", "success_rate"},
        field_path="immune",
    )
    available = raw.get("available")
    breaker = raw.get("breaker", {})
    if (
        not isinstance(available, bool)
        or not isinstance(breaker, Mapping)
        or not isinstance(breaker.get("tripped"), bool)
    ):
        _fail("invalid_type", "immune")
    _reject_unknown_keys(
        breaker,
        {"tripped", "rollbacks", "consecutive_rollbacks", "cooldown_remaining"},
        field_path="immune.breaker",
    )
    tripped = bool(breaker["tripped"])
    current_count = _count(raw.get("heals_rolled_back", 0), field_path="immune.heals_rolled_back")
    if previous_state is None:
        rollback = "none" if current_count == 0 else "unknown"
    else:
        previous_count = _count(
            previous_state.get("immune_rollbacks_total"), field_path="comparison_state.immune_rollbacks_total"
        )
        if current_count < previous_count:
            _fail("invalid_value", "immune.heals_rolled_back")
        rollback = "observed" if current_count > previous_count else "none"
    if tripped:
        immune_class = "tripped"
    elif not available:
        immune_class = "unavailable"
    elif rollback == "observed":
        immune_class = "degraded"
    elif rollback == "none":
        immune_class = "healthy"
    else:
        immune_class = "unknown"
    return {"class": immune_class, "rollback": rollback}, {"immune_rollbacks_total": current_count}


def normalize_campaign(raw: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown_keys(raw, {"campaign_id", "all_met", "signals", "failing"}, field_path="campaign")
    signals = raw.get("signals", [])
    if not isinstance(signals, list):
        _fail("invalid_type", "campaign.signals")
    failing: set[str] = set()
    for index, signal in enumerate(signals):
        if not isinstance(signal, Mapping):
            _fail("invalid_type", f"campaign.signals[{index}]")
        _reject_unknown_keys(signal, {"kind", "met", "actual", "target"}, field_path=f"campaign.signals[{index}]")
        kind = signal.get("kind")
        met = signal.get("met")
        if kind not in _CAMPAIGN_KINDS:
            _fail("unsupported_version", f"campaign.signals[{index}].kind")
        if not isinstance(met, bool):
            _fail("invalid_type", f"campaign.signals[{index}].met")
        if not met:
            failing.add(str(kind))
    if not signals:
        campaign_class = "empty"
    elif failing:
        campaign_class = "failing"
    else:
        campaign_class = "met"
    if "all_met" in raw:
        all_met = raw["all_met"]
        if not isinstance(all_met, bool):
            _fail("invalid_type", "campaign.all_met")
        expected_all_met = bool(signals) and not failing
        if all_met != expected_all_met:
            _fail("inconsistent", "campaign.all_met")
    return {"class": campaign_class, "failing_kinds": sorted(failing)}


def normalize_cetana(raw: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown_keys(
        raw,
        {"alive", "consecutive_anomalies", "frequency_hz", "last_guna", "last_health", "phase", "total_beats"},
        field_path="cetana",
    )
    alive = raw.get("alive")
    if not isinstance(alive, bool):
        _fail("invalid_type", "cetana.alive")
    anomalies = _count(raw.get("consecutive_anomalies", 0), field_path="cetana.consecutive_anomalies")
    return {"class": "unavailable" if not alive else "anomalous" if anomalies else "alive"}


def derive_output_mode(safety_sources: Mapping[str, SourceResult], *, fallback_verified: bool) -> OutputMode | None:
    required = {"health", "federation", "immune", "cetana"}
    if set(safety_sources) != required:
        _fail("invalid_schema", "safety_sources")
    health_usable = safety_sources["health"].status is SourceStatus.VALID
    federation_usable = safety_sources["federation"].status in {SourceStatus.VALID, SourceStatus.EMPTY}
    immune_usable = safety_sources["immune"].status is SourceStatus.VALID
    cetana_usable = safety_sources["cetana"].status is SourceStatus.VALID
    if not any((health_usable, federation_usable, immune_usable, cetana_usable)):
        return OutputMode.SAFE_FALLBACK if fallback_verified else None
    if all((health_usable, federation_usable, immune_usable, cetana_usable)):
        return OutputMode.CANONICAL
    return OutputMode.DEGRADED


def _exact_keys(value: object, expected: set[str], *, field_path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail("invalid_type", field_path)
    if set(value) != expected:
        _fail("invalid_schema", field_path)
    return value


def _enum_value(value: object, allowed: set[str], *, field_path: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        _fail("invalid_value", field_path)
    return value


def _nullable_count(value: object, *, field_path: str) -> int | None:
    return None if value is None else _count(value, field_path=field_path)


def _validate_observations(observations: Mapping[str, object]) -> None:
    expected_sections = {"health", "senses", "gaps", "federation", "immune", "campaign", "cetana"}
    _exact_keys(observations, expected_sections, field_path="observations")

    health = _exact_keys(observations["health"], {"class", "guna", "provider"}, field_path="observations.health")
    _enum_value(health["class"], {"healthy", "watch", "critical", "unknown"}, field_path="observations.health.class")
    _enum_value(health["guna"], {"sattva", "rajas", "tamas", "unknown"}, field_path="observations.health.guna")
    _enum_value(
        health["provider"],
        {"healthy", "degraded", "unavailable", "unknown"},
        field_path="observations.health.provider",
    )

    senses = _exact_keys(observations["senses"], {"pain", "critical_count"}, field_path="observations.senses")
    _enum_value(
        senses["pain"], {"clear", "elevated", "high", "critical", "unknown"}, field_path="observations.senses.pain"
    )
    _nullable_count(senses["critical_count"], field_path="observations.senses.critical_count")

    gaps = _exact_keys(observations["gaps"], {"active_count", "categories"}, field_path="observations.gaps")
    _nullable_count(gaps["active_count"], field_path="observations.gaps.active_count")
    categories = gaps["categories"]
    if (
        not isinstance(categories, list)
        or categories != sorted(set(categories))
        or any(category not in _GAP_CATEGORIES for category in categories)
    ):
        _fail("invalid_value", "observations.gaps.categories")

    federation = _exact_keys(
        observations["federation"],
        {"class", "alive", "suspect", "dead", "gateway"},
        field_path="observations.federation",
    )
    _enum_value(
        federation["class"],
        {"healthy", "degraded", "critical", "empty", "unknown"},
        field_path="observations.federation.class",
    )
    for count_name in ("alive", "suspect", "dead"):
        _nullable_count(federation[count_name], field_path=f"observations.federation.{count_name}")
    _enum_value(
        federation["gateway"], {"clear", "degraded", "error", "unknown"}, field_path="observations.federation.gateway"
    )

    immune = _exact_keys(observations["immune"], {"class", "rollback"}, field_path="observations.immune")
    _enum_value(
        immune["class"],
        {"healthy", "degraded", "tripped", "unavailable", "unknown"},
        field_path="observations.immune.class",
    )
    _enum_value(immune["rollback"], {"none", "observed", "unknown"}, field_path="observations.immune.rollback")

    campaign = _exact_keys(observations["campaign"], {"class", "failing_kinds"}, field_path="observations.campaign")
    _enum_value(campaign["class"], {"met", "failing", "empty", "unknown"}, field_path="observations.campaign.class")
    failing_kinds = campaign["failing_kinds"]
    if (
        not isinstance(failing_kinds, list)
        or failing_kinds != sorted(set(failing_kinds))
        or any(kind not in _CAMPAIGN_KINDS for kind in failing_kinds)
    ):
        _fail("invalid_value", "observations.campaign.failing_kinds")

    cetana = _exact_keys(observations["cetana"], {"class"}, field_path="observations.cetana")
    _enum_value(
        cetana["class"], {"alive", "anomalous", "unavailable", "unknown"}, field_path="observations.cetana.class"
    )


def _validate_comparison_state(comparison_state: Mapping[str, int | None]) -> None:
    expected = {
        "gateway_errors_total",
        "gateway_rejected_parse_total",
        "gateway_rejected_validate_total",
        "immune_rollbacks_total",
    }
    if set(comparison_state) != expected:
        _fail("invalid_schema", "comparison_state")
    for key, value in comparison_state.items():
        _nullable_count(value, field_path=f"comparison_state.{key}")


def _validate_mode_sources(sources: Mapping[str, SourceResult], mode: OutputMode) -> None:
    required_valid = {"constitution", "context_schema", "repository"}
    degraded_statuses = {
        SourceStatus.UNAVAILABLE,
        SourceStatus.INVALID,
        SourceStatus.STALE,
        SourceStatus.UNSAFE,
        SourceStatus.UNSUPPORTED,
    }
    if mode in {OutputMode.CANONICAL, OutputMode.DEGRADED} and any(
        sources[source_id].status is not SourceStatus.VALID for source_id in required_valid
    ):
        _fail("invalid_schema", "payload.source_status")
    has_degradation = any(source.status in degraded_statuses for source in sources.values())
    if mode is OutputMode.CANONICAL and has_degradation:
        _fail("inconsistent", "payload.mode")
    if mode is OutputMode.DEGRADED and not has_degradation:
        _fail("inconsistent", "payload.mode")


def validate_payload_core(model: Mapping[str, object]) -> None:
    """Validate a materialized SemanticPayloadCore v1 model."""
    payload = _exact_keys(
        model,
        {"schema", "contract", "mode", "source_status", "observations"},
        field_path="payload",
    )
    if payload["schema"] != "steward.context.payload/v1":
        _fail("invalid_schema", "payload.schema")

    contract = _exact_keys(
        payload["contract"],
        {"c0_version", "c0_sha256", "c0", "orientation_sha256", "orientation"},
        field_path="payload.contract",
    )
    if contract["c0_version"] != "c0/v1" or not isinstance(contract["c0"], str):
        _fail("invalid_schema", "payload.contract.c0")
    c0 = contract["c0"]
    if validate_public_safe_text(c0, field_path="payload.contract.c0", multiline=True) != c0:
        _fail("inconsistent", "payload.contract.c0")
    if not c0.endswith("\n") or c0.endswith("\n\n"):
        _fail("invalid_value", "payload.contract.c0")
    _validate_hash(contract["c0_sha256"], 64, field_path="payload.contract.c0_sha256")
    if contract["c0_sha256"] != hashlib.sha256(c0.encode("utf-8")).hexdigest():
        _fail("inconsistent", "payload.contract.c0_sha256")

    orientation = contract["orientation"]
    orientation_hash = contract["orientation_sha256"]
    if orientation is None:
        if orientation_hash is not None:
            _fail("inconsistent", "payload.contract.orientation_sha256")
    else:
        if not isinstance(orientation, str):
            _fail("invalid_type", "payload.contract.orientation")
        if (
            validate_public_safe_text(orientation, field_path="payload.contract.orientation", multiline=True)
            != orientation
        ):
            _fail("inconsistent", "payload.contract.orientation")
        if orientation and (not orientation.endswith("\n") or orientation.endswith("\n\n")):
            _fail("invalid_value", "payload.contract.orientation")
        _validate_hash(orientation_hash, 64, field_path="payload.contract.orientation_sha256")
        if orientation_hash != hashlib.sha256(orientation.encode("utf-8")).hexdigest():
            _fail("inconsistent", "payload.contract.orientation_sha256")

    mode = _enum_value(payload["mode"], {item.value for item in OutputMode}, field_path="payload.mode")
    source_status = payload["source_status"]
    if not isinstance(source_status, list) or len(source_status) != len(_PARTICIPATING_SOURCES):
        _fail("invalid_schema", "payload.source_status")
    statuses: dict[str, str] = {}
    for index, source_id in enumerate(_PARTICIPATING_SOURCES):
        item = _exact_keys(
            source_status[index],
            {"source_id", "status", "source_mode", "age_bucket"},
            field_path=f"payload.source_status.{index}",
        )
        if item["source_id"] != source_id:
            _fail("inconsistent", f"payload.source_status.{index}.source_id")
        statuses[source_id] = _enum_value(
            item["status"],
            {status.value for status in SourceStatus},
            field_path=f"payload.source_status.{source_id}.status",
        )
        if item["source_mode"] != _SOURCE_MODE[source_id]:
            _fail("inconsistent", f"payload.source_status.{source_id}.source_mode")
        _enum_value(item["age_bucket"], set(_AGE_BUCKETS), field_path=f"payload.source_status.{source_id}.age_bucket")

    required_valid = {"constitution", "context_schema", "repository"}
    if mode in {OutputMode.CANONICAL.value, OutputMode.DEGRADED.value} and any(
        statuses[source_id] != SourceStatus.VALID.value for source_id in required_valid
    ):
        _fail("invalid_schema", "payload.source_status")
    degraded = {
        SourceStatus.UNAVAILABLE.value,
        SourceStatus.INVALID.value,
        SourceStatus.STALE.value,
        SourceStatus.UNSAFE.value,
        SourceStatus.UNSUPPORTED.value,
    }
    has_degradation = any(status in degraded for status in statuses.values())
    if mode == OutputMode.CANONICAL.value and has_degradation:
        _fail("inconsistent", "payload.mode")
    if mode == OutputMode.DEGRADED.value and not has_degradation:
        _fail("inconsistent", "payload.mode")

    _validate_observations(payload["observations"])
    canonical_json_bytes(dict(payload))


def validate_snapshot_model(model: Mapping[str, object]) -> None:
    """Validate a materialized NormalizedSnapshot v1 model."""
    snapshot = _exact_keys(
        model,
        {
            "schema",
            "repository",
            "generator",
            "assembled_at",
            "constitution",
            "orientation",
            "comparison_state",
            "sources",
            "observations",
        },
        field_path="snapshot",
    )
    if snapshot["schema"] != "steward.context.snapshot/v1":
        _fail("invalid_schema", "snapshot.schema")
    repository = _exact_keys(snapshot["repository"], {"name", "head"}, field_path="snapshot.repository")
    if not isinstance(repository["name"], str) or not _REPOSITORY_NAME.fullmatch(repository["name"]):
        _fail("invalid_value", "snapshot.repository.name")
    _validate_hash(repository["head"], 40, field_path="snapshot.repository.head")
    generator = _exact_keys(snapshot["generator"], {"schema", "repository", "commit"}, field_path="snapshot.generator")
    if generator["schema"] != "steward.context.generator/v1":
        _fail("invalid_schema", "snapshot.generator.schema")
    if generator["repository"] != repository["name"]:
        _fail("inconsistent", "snapshot.generator.repository")
    _validate_hash(generator["commit"], 40, field_path="snapshot.generator.commit")
    assembled_at = _validate_timestamp(snapshot["assembled_at"], field_path="snapshot.assembled_at")

    constitution = _exact_keys(
        snapshot["constitution"],
        {"version", "sha256", "source_blob", "reviewed_at_commit"},
        field_path="snapshot.constitution",
    )
    if constitution["version"] != "c0/v1":
        _fail("invalid_schema", "snapshot.constitution.version")
    _validate_hash(constitution["sha256"], 64, field_path="snapshot.constitution.sha256")
    _validate_hash(constitution["source_blob"], 40, field_path="snapshot.constitution.source_blob")
    _validate_hash(constitution["reviewed_at_commit"], 40, field_path="snapshot.constitution.reviewed_at_commit")
    orientation = _exact_keys(snapshot["orientation"], {"sha256"}, field_path="snapshot.orientation")
    if orientation["sha256"] is not None:
        _validate_hash(orientation["sha256"], 64, field_path="snapshot.orientation.sha256")

    comparison_state = _exact_keys(
        snapshot["comparison_state"],
        {
            "gateway_errors_total",
            "gateway_rejected_parse_total",
            "gateway_rejected_validate_total",
            "immune_rollbacks_total",
        },
        field_path="snapshot.comparison_state",
    )
    _validate_comparison_state(comparison_state)

    sources = snapshot["sources"]
    expected_sources = sorted(_ALL_SOURCES)
    if not isinstance(sources, list) or len(sources) != len(expected_sources):
        _fail("invalid_schema", "snapshot.sources")
    for index, source_id in enumerate(expected_sources):
        item = _exact_keys(
            sources[index],
            {
                "source_id",
                "trust_zone",
                "status",
                "source_mode",
                "observed_at",
                "age_bucket",
                "schema_version",
                "error_code",
            },
            field_path=f"snapshot.sources.{index}",
        )
        if item["source_id"] != source_id:
            _fail("inconsistent", f"snapshot.sources.{index}.source_id")
        if item["trust_zone"] != _SOURCE_TRUST[source_id]:
            _fail("inconsistent", f"snapshot.sources.{source_id}.trust_zone")
        if item["source_mode"] != _SOURCE_MODE[source_id]:
            _fail("inconsistent", f"snapshot.sources.{source_id}.source_mode")
        status = _enum_value(
            item["status"], {status.value for status in SourceStatus}, field_path=f"snapshot.sources.{source_id}.status"
        )
        _enum_value(item["age_bucket"], set(_AGE_BUCKETS), field_path=f"snapshot.sources.{source_id}.age_bucket")
        if (
            status in {SourceStatus.VALID.value, SourceStatus.EMPTY.value}
            and item["source_mode"] in {"live", "derived"}
            and item["observed_at"] is None
        ):
            _fail("invalid_value", f"snapshot.sources.{source_id}.observed_at")
        if item["observed_at"] is not None:
            observed_at = _validate_timestamp(
                item["observed_at"], field_path=f"snapshot.sources.{source_id}.observed_at"
            )
            if observed_at > assembled_at:
                _fail("invalid_value", f"snapshot.sources.{source_id}.observed_at")
        if item["schema_version"] is not None:
            _validate_ascii_identifier(
                item["schema_version"], field_path=f"snapshot.sources.{source_id}.schema_version"
            )
        if item["error_code"] is not None and item["error_code"] not in _ERROR_CODES:
            _fail("unsupported_version", f"snapshot.sources.{source_id}.error_code")

    _validate_observations(snapshot["observations"])
    canonical_json_bytes(dict(snapshot))


def build_payload_core(
    conventions: ParsedConventions,
    sources: Mapping[str, SourceResult],
    observations: Mapping[str, object],
    mode: OutputMode,
) -> dict[str, object]:
    missing = set(_PARTICIPATING_SOURCES) - set(sources)
    if missing:
        _fail("provenance_missing", "payload.source_status")
    _validate_observations(observations)
    _validate_mode_sources(sources, mode)
    source_status = []
    for source_id in _PARTICIPATING_SOURCES:
        source = sources[source_id]
        if source.source_id != source_id:
            _fail("inconsistent", f"payload.source_status.{source_id}")
        source_status.append(
            {
                "source_id": source.source_id,
                "status": source.status.value,
                "source_mode": source.source_mode,
                "age_bucket": source.age_bucket,
            }
        )
    orientation = conventions.orientation
    core = {
        "schema": "steward.context.payload/v1",
        "contract": {
            "c0_version": conventions.c0_version,
            "c0_sha256": hashlib.sha256(conventions.c0.encode("utf-8")).hexdigest(),
            "c0": conventions.c0,
            "orientation_sha256": hashlib.sha256(orientation.encode("utf-8")).hexdigest()
            if orientation is not None
            else None,
            "orientation": orientation,
        },
        "mode": mode.value,
        "source_status": source_status,
        "observations": dict(observations),
    }
    validate_payload_core(core)
    return core


def build_snapshot(
    *,
    repository_name: str,
    repository_head: str,
    generator_commit: str,
    assembled_at: str,
    conventions: ParsedConventions,
    attestation: ConstitutionAttestation,
    sources: Mapping[str, SourceResult],
    observations: Mapping[str, object],
    comparison_state: Mapping[str, int | None],
) -> dict[str, object]:
    if set(sources) != _ALL_SOURCES:
        _fail("provenance_missing", "snapshot.sources")
    if not isinstance(repository_name, str) or not _REPOSITORY_NAME.fullmatch(repository_name):
        _fail("invalid_value", "snapshot.repository.name")
    _validate_hash(repository_head, 40, field_path="snapshot.repository.head")
    _validate_hash(generator_commit, 40, field_path="snapshot.generator.commit")
    _validate_timestamp(assembled_at, field_path="snapshot.assembled_at")
    c0_sha256 = hashlib.sha256(conventions.c0.encode("utf-8")).hexdigest()
    if attestation.c0_sha256 != c0_sha256:
        _fail("inconsistent", "snapshot.constitution.sha256")
    _validate_attestation(attestation)
    _validate_observations(observations)
    _validate_comparison_state(comparison_state)
    source_snapshots = []
    for source_id in sorted(sources):
        source = sources[source_id]
        if source.source_id != source_id:
            _fail("inconsistent", f"snapshot.sources.{source_id}")
        if source.observed_at is not None and source.observed_at > assembled_at:
            _fail("invalid_value", f"snapshot.sources.{source_id}.observed_at")
        source_snapshots.append(
            {
                "source_id": source.source_id,
                "trust_zone": source.trust_zone.value,
                "status": source.status.value,
                "source_mode": source.source_mode,
                "observed_at": source.observed_at,
                "age_bucket": source.age_bucket,
                "schema_version": source.schema_version,
                "error_code": source.error_code,
            }
        )
    snapshot = {
        "schema": "steward.context.snapshot/v1",
        "repository": {"name": repository_name, "head": repository_head},
        "generator": {
            "schema": "steward.context.generator/v1",
            "repository": repository_name,
            "commit": generator_commit,
        },
        "assembled_at": assembled_at,
        "constitution": {
            "version": conventions.c0_version,
            "sha256": c0_sha256,
            "source_blob": attestation.source_blob,
            "reviewed_at_commit": attestation.reviewed_at_commit,
        },
        "orientation": {
            "sha256": hashlib.sha256(conventions.orientation.encode("utf-8")).hexdigest()
            if conventions.orientation is not None
            else None
        },
        "comparison_state": {key: value for key, value in sorted(comparison_state.items())},
        "sources": source_snapshots,
        "observations": dict(observations),
    }
    validate_snapshot_model(snapshot)
    return snapshot


def _validate_attestation(attestation: ConstitutionAttestation) -> None:
    if attestation.schema != "steward.context.constitution-attestation/v1" or attestation.status != "verified":
        _fail("invalid_schema", "constitution_attestation")
    _validate_hash(attestation.c0_sha256, 64, field_path="constitution_attestation.c0_sha256")
    _validate_hash(attestation.source_blob, 40, field_path="constitution_attestation.source_blob")
    _validate_hash(attestation.reviewed_at_commit, 40, field_path="constitution_attestation.reviewed_at_commit")


def _valid_previous(previous: PreviousPublishedRecord) -> bool:
    try:
        if previous.record_schema != "steward.context.published-record/v1":
            return False
        if previous.payload_schema != "steward.context.payload/v1" or previous.mode is OutputMode.PREVIEW:
            return False
        _validate_hash(previous.payload_hash, 64, field_path="previous.payload_hash")
        _validate_hash(previous.c0_sha256, 64, field_path="previous.c0_sha256")
        if not re.fullmatch(r"ctxsnap-v1:[0-9a-f]{64}", previous.snapshot_id):
            return False
        if set(previous.consumer_outputs) != {"agents", "claude"}:
            return False
        outputs = list(previous.consumer_outputs.values())
        for value in outputs:
            _validate_hash(value, 64, field_path="previous.consumer_outputs")
        if outputs[0] != outputs[1]:
            return False
        expected_comparison = {
            "gateway_errors_total",
            "gateway_rejected_parse_total",
            "gateway_rejected_validate_total",
            "immune_rollbacks_total",
        }
        if set(previous.comparison_state) != expected_comparison:
            return False
        for key, value in previous.comparison_state.items():
            _count(value, field_path=f"previous.comparison_state.{key}")
    except ContractViolation:
        return False
    return True


def decide_publish(
    candidate_payload_hash: str,
    candidate_c0_sha256: str,
    attestation: ConstitutionAttestation,
    previous: PreviousPublishedRecord | None,
    mode: OutputMode,
    *,
    valid: bool = True,
) -> ContractDecision:
    if not valid or not isinstance(mode, OutputMode):
        return ContractDecision(Decision.BLOCKED, "candidate_invalid")
    try:
        _validate_hash(candidate_payload_hash, 64, field_path="candidate.payload_hash")
        _validate_hash(candidate_c0_sha256, 64, field_path="candidate.c0_sha256")
    except ContractViolation:
        return ContractDecision(Decision.BLOCKED, "candidate_invalid")
    if mode is OutputMode.PREVIEW:
        return ContractDecision(Decision.BLOCKED, "preview_not_canonical")
    try:
        _validate_attestation(attestation)
    except ContractViolation:
        return ContractDecision(Decision.MANUAL_REVIEW, "constitution_attestation_invalid")
    if attestation.c0_sha256 != candidate_c0_sha256:
        return ContractDecision(Decision.MANUAL_REVIEW, "constitution_attestation_mismatch")
    if previous is None:
        return ContractDecision(Decision.PUBLISH, "initial_attested_payload")
    if not _valid_previous(previous):
        return ContractDecision(Decision.BLOCKED, "previous_record_invalid")
    if previous.c0_sha256 != candidate_c0_sha256:
        return ContractDecision(Decision.MANUAL_REVIEW, "constitution_changed")
    if previous.payload_hash == candidate_payload_hash:
        return ContractDecision(Decision.NO_OP, "semantic_payload_unchanged")
    return ContractDecision(Decision.PUBLISH, "semantic_payload_changed")
