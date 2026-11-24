import json
from decimal import Decimal

import pytest
from google.genai import types

from apps.chatbot import agent, prompts, services
from apps.chatbot.llm import get_llm
from apps.chatbot.llm.base import LLMError, LLMReply, ToolCall, Turn
from apps.chatbot.llm.fake import FakeLLM
from apps.chatbot.llm.gemini import GeminiClient
from apps.chatbot.models import ChatMessage
from tests.factories import ClientFactory, EventFactory, ItemFactory

pytestmark = pytest.mark.django_db


def call(name, raw=None, **args):
    return LLMReply(tool_calls=[ToolCall(name=name, args=args, id="c1")], raw=raw)


def run(conversation):
    services.process_conversation(conversation.pk)
    conversation.refresh_from_db()


def test_tool_round_trip(conversation, inbound, outbox):
    ItemFactory(name="Soda", kind="drink", unit="bottle", unit_price=Decimal("1500"))
    inbound("price of soda?")
    FakeLLM.script(call("search_catalog", query="soda"), LLMReply(text="Soda is TZS 1,500."))
    run(conversation)
    assert outbox[0]["text"] == "Soda is TZS 1,500."
    result = FakeLLM.calls[1]["turns"][-1].results[0]
    assert (result["id"], result["name"]) == ("c1", "search_catalog")
    assert "TZS 1,500" in json.dumps(result["response"])


def test_raw_model_content_is_replayed_unchanged(conversation, inbound):
    raw = {"role": "model", "parts": [{"thought_signature": "c2ln"}]}
    inbound("areas?")
    FakeLLM.script(call("list_service_areas", raw=raw), LLMReply(text="None."))
    run(conversation)
    inbound("again")
    FakeLLM.script(LLMReply(text="ok"))
    run(conversation)
    assert FakeLLM.calls[1]["turns"][1].raw == raw
    assert FakeLLM.calls[2]["turns"][1].raw == raw


def test_max_rounds_then_fallback(conversation, inbound, outbox):
    inbound()
    FakeLLM.script(*[call("list_service_areas")] * (agent.MAX_ROUNDS + 1))
    run(conversation)
    assert len(FakeLLM.calls) == agent.MAX_ROUNDS + 1
    assert outbox[0]["text"] == prompts.text("fallback", "en")


@pytest.mark.parametrize(("text", "language"), [("hello there", "en"), ("habari, bei gani?", "sw")])
@pytest.mark.parametrize("error", [LLMError("down"), RuntimeError("bug")])
def test_failure_sends_fallback_in_language(conversation, inbound, outbox, text, language, error):
    message = inbound(text)
    FakeLLM.script(error)
    run(conversation)
    assert outbox[0]["text"] == prompts.text("fallback", language)
    message.refresh_from_db()
    assert message.status == "failed"
    inbound("again")
    FakeLLM.script(LLMReply(text="ok"))
    run(conversation)
    assert FakeLLM.calls[1]["turns"][0].text == text  # not lost


def test_history_window_starts_at_a_user_message(conversation, inbound):
    for i in range(12):
        inbound(f"m{i}")
        FakeLLM.script(call("list_service_areas"), LLMReply(text="ok"))
        run(conversation)
    turns = FakeLLM.calls[-2]["turns"]
    assert len(turns) <= agent.HISTORY
    assert turns[0].role == "user"
    assert turns[-1].text == "m11"


def test_unknown_tool_is_reported_to_the_model(conversation, inbound):
    inbound()
    FakeLLM.script(call("drop_tables"), LLMReply(text="ok"))
    run(conversation)
    assert "error" in FakeLLM.calls[1]["turns"][-1].results[0]["response"]


@pytest.mark.parametrize(
    "lie", ["It is TZS 9,999.", "Ni shilingi 9999", "9,999 only", "9999/=", "elfu 9 tu", "9k Tsh"]
)
def test_invented_price_is_blocked(conversation, inbound, outbox, lie):
    inbound("price?")
    FakeLLM.script(LLMReply(text=lie), LLMReply(text=lie))
    run(conversation)
    assert outbox[0]["text"] == prompts.text("fallback", "en")


def test_invented_price_can_be_corrected(conversation, inbound, outbox):
    inbound("price?")
    FakeLLM.script(LLMReply(text="TZS 9,999"), LLMReply(text="Which item?"))
    run(conversation)
    assert outbox[0]["text"] == "Which item?"


def test_numbers_that_are_not_prices_pass(conversation, inbound, outbox):
    inbound("my budget is 500000 for 100 people")
    text = "100 guests on 2027-01-05, budget TZS 500,000. Ref EVT-261124-AB12."
    FakeLLM.script(LLMReply(text=text))
    run(conversation)
    assert outbox[0]["text"] == text


def test_quantities_from_tools_do_not_license_prices(conversation, inbound, outbox):
    ItemFactory(name="Pilau", min_quantity=50)
    inbound("pilau?")
    FakeLLM.script(
        call("search_catalog", query="pilau"), LLMReply(text="TZS 50"), LLMReply(text="TZS 50")
    )
    run(conversation)
    assert outbox[0]["text"] == prompts.text("fallback", "en")


def test_language_follows_the_user(conversation, inbound):
    inbound("Nataka chakula cha harusi")
    FakeLLM.script(LLMReply(text="Sawa"), LLMReply(text="ok"), LLMReply(text="ok"))
    run(conversation)
    assert conversation.language == "sw"
    inbound("2")  # undecidable: unchanged
    run(conversation)
    assert conversation.language == "sw"
    inbound("I want to book the food please")
    run(conversation)
    assert conversation.language == "en"


def test_prompt_knows_the_sender_and_their_events(conversation, inbound):
    user = ClientFactory(phone="+255712345678", full_name="Asha Juma")
    event = EventFactory(client=user)
    other = EventFactory()
    inbound()
    FakeLLM.script(LLMReply(text="ok"))
    run(conversation)
    system = FakeLLM.calls[0]["system"]
    assert "Asha Juma" in system
    assert str(event.pk) in system
    assert str(other.pk) not in system
    assert conversation.user == user


def test_finished_tool_round_is_not_repeated(conversation, inbound):
    """A worker that died after a tool round resumes after it."""
    message = inbound()
    for role, payload in (("model", {"raw": None}), ("tool", {"results": []})):
        ChatMessage.objects.create(
            conversation=conversation,
            direction="out",
            role=role,
            reply_to=message,
            payload=payload,
            status="processed",
        )
    FakeLLM.script(LLMReply(text="ok"))
    run(conversation)
    assert [t.role for t in FakeLLM.calls[0]["turns"]] == ["user", "model", "tool"]


# --- Gemini adapter ---------------------------------------------------------


class StubModels:
    def __init__(self, result):
        self.result, self.kwargs = result, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def gemini(result):
    client = GeminiClient.__new__(GeminiClient)
    client.models, client.model = StubModels(result), "m"
    return client


def response(*parts):
    content = types.Content(role="model", parts=list(parts))
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


def test_gemini_signature_survives_json_storage():
    part = types.Part(
        function_call=types.FunctionCall(name="list_vendors", args={"a": 1}, id="x"),
        thought_signature=b"\x00\xffsig",
    )
    reply = gemini(response(part)).generate(system="s", turns=[Turn("user", "hi")], tools=[])
    assert reply.tool_calls == [ToolCall("list_vendors", {"a": 1}, "x")]
    raw = json.loads(json.dumps(reply.raw))
    client = gemini(response(types.Part(text="done")))
    results = [{"id": "x", "name": "list_vendors", "response": {"ok": True}}]
    turns = [Turn("user", "hi"), Turn("model", raw=raw), Turn("tool", results=results)]
    assert client.generate(system="s", turns=turns, tools=[]).text == "done"
    contents = client.models.kwargs["contents"]
    assert contents[1].parts[0].thought_signature == b"\x00\xffsig"
    answer = contents[2].parts[0].function_response
    assert (answer.id, answer.name, answer.response) == ("x", "list_vendors", {"ok": True})
    assert client.models.kwargs["config"].automatic_function_calling.disable is True


def test_gemini_thoughts_are_not_shown():
    reply = gemini(response(types.Part(text="hmm", thought=True), types.Part(text="Hi"))).generate(
        system="s", turns=[Turn("user", "hi")], tools=[]
    )
    assert reply.text == "Hi"


@pytest.mark.parametrize(
    "result", [RuntimeError("secret"), types.GenerateContentResponse(candidates=[]), response()]
)
def test_gemini_failures_become_llm_error(result):
    with pytest.raises(LLMError) as exc:
        gemini(result).generate(system="s", turns=[Turn("user", "hi")], tools=[])
    assert "secret" not in str(exc.value)


def test_llm_factory(settings):
    assert isinstance(get_llm(), FakeLLM)
    settings.LLM_PROVIDER, settings.GEMINI_API_KEY = "gemini", "k"
    assert isinstance(get_llm(), GeminiClient)
