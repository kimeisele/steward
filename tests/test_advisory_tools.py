"""Tests for fail-open Buddhi tool suggestions."""

from dataclasses import replace
from unittest.mock import patch

from steward.agent import StewardAgent
from tests.fakes import FakeLLM, FakeResponse


def _narrow_directive(agent: StewardAgent):
    directive = agent._buddhi.pre_flight("inspect the failing test", round_num=0)
    tool_name = sorted(directive.tool_names)[0]
    return replace(directive, tool_names=frozenset({tool_name}))


def test_hint_is_present_for_narrow_classification():
    """A narrow classification appears as an advisory round-context hint."""
    llm = FakeLLM([FakeResponse(content='{"response": "done"}')])
    agent = StewardAgent(provider=llm)
    directive = _narrow_directive(agent)

    with patch.object(agent._buddhi, "pre_flight", return_value=directive):
        agent.run_sync("inspect the failing test")

    messages = agent._provider.last_call["messages"]
    context = "\n".join(str(message["content"]) for message in messages)
    assert "[Buddhi] For this task, these tools may be useful:" in context
    assert f"{next(iter(directive.tool_names))}." in context
    assert "All other tools remain fully available." in context


def test_no_tool_is_ever_removed():
    """Fail-open behavior keeps every registered tool visible to the model.

    This guard must fail if an advisory suggestion is later turned into a
    restrictive filter, even when classification is forced to one tool.
    """
    llm = FakeLLM(
        [
            FakeResponse(content='{"response": "done"}'),
            FakeResponse(content='{"response": "done"}'),
        ]
    )
    agent = StewardAgent(provider=llm)
    all_tool_names = {description["name"] for description in agent._registry.get_tool_descriptions()}
    directive = _narrow_directive(agent)

    with patch.object(agent._buddhi, "pre_flight", return_value=directive):
        for user_message in ("inspect the failing test", "implement the fix"):
            agent.run_sync(user_message)

    for call in llm.calls:
        system_prompt = str(call["messages"][0]["content"])
        for tool_name in all_tool_names:
            assert tool_name in system_prompt


def test_hint_does_not_enter_conversation():
    """The transient hint reaches the model but not the conversation log."""
    llm = FakeLLM([FakeResponse(content='{"response": "done"}')])
    agent = StewardAgent(provider=llm)
    directive = _narrow_directive(agent)

    with patch.object(agent._buddhi, "pre_flight", return_value=directive):
        agent.run_sync("inspect the failing test")

    stored_messages = agent.conversation.messages
    assert len(stored_messages) == 3
    assert all("[Buddhi]" not in message.content for message in stored_messages)
    sent_system_prompt = llm.last_call["messages"][0]["content"]
    assert "[Buddhi] For this task, these tools may be useful:" in sent_system_prompt
