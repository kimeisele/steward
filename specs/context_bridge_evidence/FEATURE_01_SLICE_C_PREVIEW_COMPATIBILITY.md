# Feature 01 Slice C — Legacy Preview Compatibility Prerequisite

Status: **Implemented and verified; prerequisite merged**

Pinned base: `05616b4a90f133c45ae74ab04869321d26b4203c`

## 1. Blocking evidence

PR `#552` proved the exact Constitution source bytes, but its replacement briefing test
was a false positive. It asserted only that some preview string existed and no Root-Datei
was written.

The test did not prove that the versioned Orientation was consumed because:

- `_load_orientation()` does not call `parse_conventions()`;
- it treats `<!-- steward-context:c0:v1:begin -->` as ordinary content and can expose the
  complete C0 block as legacy Orientation;
- `BriefingPipeline._render_all()` catches every stage exception, so an indirect preview
  assertion can remain green when `OrientationStage` fails completely.

Slice C must therefore remain draft until a marker-aware compatibility adapter exists.

## 2. Required sequencing

1. Merge this evidence correction.
2. Implement the adapter in a separate prerequisite PR.
3. Keep the old unmarked Source unchanged while validating the adapter.
4. Rebase and rebuild Slice C on the merged adapter.
5. Require direct loader assertions in addition to preview/no-write assertions.

## 3. Exact prerequisite scope

Only these paths may change in the adapter PR:

```text
steward/briefing_stages.py
tests/test_briefing.py
```

No Constitution source, Root-Datei, writer, workflow, setting, runtime state or delivery
path may change.

## 4. Loader contract

For `.steward/conventions.md`:

- missing or empty file returns `""`;
- a valid versioned source is parsed by the existing strict `parse_conventions()` and
  returns only `ParsedConventions.orientation`, never C0 or marker text;
- a valid empty versioned Orientation returns `""`;
- a source containing any Steward context marker but failing strict parsing fails closed
  to `""` and emits a safe warning without source content;
- an unmarked legacy source retains the current comment-skipping behavior until Slice C
  lands;
- unreadable or invalid UTF-8 input returns `""` and emits no raw content.

The generic stage exception boundary is not changed in this prerequisite. Tests must call
`_load_orientation()` directly so that this boundary cannot convert a loader regression
into a green test.

## 5. Required red/green tests

Before the product patch, direct tests must fail for:

1. valid C0 plus non-empty Orientation returns only Orientation;
2. valid C0 plus empty Orientation returns `""`;
3. malformed/unknown marker source fails closed rather than becoming Orientation;
4. C0 text and marker text never appear in the loader result.

Existing tests must remain green for missing, empty and unmarked legacy sources. A preview
test may additionally prove no Root-Datei is written, but it is not a substitute for the
direct loader assertions.

## 6. Effect on PR #552

The head `1b6cb74849a240ac7be9318eb4ffa5f616253fee` is rejected and has no operator approval.
After the prerequisite merge, Slice C must be rebased and its briefing test replaced with
a direct assertion that the real migrated source yields empty Orientation. All hashes and
checks must then be repinned in a new HITL packet.

## 7. Verified result

- Implementation PR: `#559`
- Merge commit: `2c4ac9c12445bc791423f4cdd830959987c79ccf`
- Changed paths: exactly `steward/briefing_stages.py` and `tests/test_briefing.py`
- Red proof: five direct failures covering C0 leakage, empty Orientation, malformed
  structured input and invalid UTF-8
- Local green proof: nine direct loader tests and 102 adjacent tests
- CI: Python 3.11, Python 3.12, Lint and Security green

The old unmarked Source remained unchanged in this prerequisite. Slice C was subsequently
rebuilt into two clean commits: direct red integration contracts first, exact Source bytes
second. Its final remote head remains subject to a new CI run and operator review after
the current continuity update is merged.
