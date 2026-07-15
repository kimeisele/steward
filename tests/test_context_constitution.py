"""Contract tests for the reviewed Context Bridge constitution source."""

from __future__ import annotations

import hashlib
from pathlib import Path

from steward.context_contract import (
    C0_BEGIN,
    C0_END,
    ORIENTATION_BEGIN,
    ORIENTATION_END,
    parse_conventions,
)

ROOT = Path(__file__).parents[1]
SPEC_PATH = ROOT / "specs" / "CONTEXT_BRIDGE_FEATURE_00.md"
SOURCE_PATH = ROOT / ".steward" / "conventions.md"

EXPECTED_C0_BYTES = 1_860
EXPECTED_C0_SHA256 = "f23ab40415edf4947f12fd8ff98cf13aa8f4fbfffe029ae10aa6111fc04976a3"
EXPECTED_SOURCE_BYTES = 2_023
EXPECTED_SOURCE_SHA256 = "0afe95c392ba611ad40302e13a5d013913fca1910423fe4ea18c663cd780aff5"
EXPECTED_SOURCE_GIT_BLOB = "f428d5856a5c525e002c301890777748effbeb4e"


def normative_c0() -> str:
    spec = SPEC_PATH.read_text(encoding="utf-8")
    section_start = spec.index("## 7. Exakter C0-v1-Zieltext")
    fence_start = spec.index("```markdown\n", section_start) + len("```markdown\n")
    fence_end = spec.index("\n```", fence_start)
    return spec[fence_start:fence_end].rstrip("\n") + "\n"


def expected_source() -> bytes:
    return (
        f"{C0_BEGIN}\n{normative_c0().rstrip(chr(10))}\n{C0_END}\n\n{ORIENTATION_BEGIN}\n{ORIENTATION_END}\n"
    ).encode("utf-8")


def git_blob_hash(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def test_source_is_exact_reviewed_constitution_candidate():
    source = SOURCE_PATH.read_bytes()
    expected = expected_source()

    assert len(normative_c0().encode("utf-8")) == EXPECTED_C0_BYTES
    assert hashlib.sha256(normative_c0().encode("utf-8")).hexdigest() == EXPECTED_C0_SHA256
    assert len(expected) == EXPECTED_SOURCE_BYTES
    assert hashlib.sha256(expected).hexdigest() == EXPECTED_SOURCE_SHA256
    assert git_blob_hash(expected) == EXPECTED_SOURCE_GIT_BLOB
    assert source == expected


def test_source_parses_to_exact_c0_and_empty_versioned_orientation():
    parsed = parse_conventions(SOURCE_PATH.read_bytes())

    assert parsed.c0 == normative_c0()
    assert parsed.c0_version == "c0/v1"
    assert parsed.orientation == ""
    assert parsed.orientation_version == "orientation/v1"


def test_source_excludes_legacy_runtime_persona_and_writer_claims():
    source = SOURCE_PATH.read_text(encoding="utf-8")

    for forbidden in (
        "You are Steward",
        "Your North Star",
        "0.1Hz",
        "0.5Hz",
        "2Hz",
        "write CLAUDE.md",
        "included verbatim in the generated CLAUDE.md",
    ):
        assert forbidden not in source
