from unittest.mock import patch

from steward.hooks.moksha_bridge import MokshaContextBridgeHook
from steward.phase_hook import PhaseContext


def test_context_write_never_calls_legacy_root_writer(tmp_path):
    root = tmp_path / "CLAUDE.md"
    original = b"# pinned legacy context\n"
    root.write_bytes(original)
    hook = MokshaContextBridgeHook()
    ctx = PhaseContext(cwd=str(tmp_path))

    with (
        patch("steward.context_bridge.assemble_context", return_value={}),
        patch("steward.context_bridge.write_context_json", return_value=True),
        patch("steward.briefing.write_claude_md") as legacy_writer,
    ):
        hook.execute(ctx)

    legacy_writer.assert_not_called()
    assert ctx.operations == ["moksha_context_bridge:context_json"]
    assert root.read_bytes() == original


def test_context_write_does_not_create_missing_root(tmp_path):
    hook = MokshaContextBridgeHook()
    ctx = PhaseContext(cwd=str(tmp_path))

    with (
        patch("steward.context_bridge.assemble_context", return_value={}),
        patch("steward.context_bridge.write_context_json", return_value=True),
    ):
        hook.execute(ctx)

    assert ctx.operations == ["moksha_context_bridge:context_json"]
    assert not (tmp_path / "CLAUDE.md").exists()
