import pytest

from app.intent_parser import IntentParseError, IntentParser
from app.models import IntentType, ParsedIntent
from app.ollama_client import OllamaError


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.schemas = []

    async def generate_json(self, system, prompt, schema):
        self.schemas.append(schema)
        return next(self.responses)


class FailingClient:
    def __init__(self):
        self.calls = 0

    async def generate_json(self, system, prompt, schema):
        self.calls += 1
        raise OllamaError("Local language model timed out after 90 seconds")


@pytest.mark.asyncio
async def test_valid_schema():
    client = FakeClient(['{"intent":"create_reminder","title":"Pay Amex","date_expression":"tomorrow","time":"20:00","confidence":0.98}'])
    parser = IntentParser(client, "Asia/Singapore")
    assert (await parser.parse("remind me")).intent == IntentType.CREATE_REMINDER
    assert client.schemas[0]["properties"]["intent"]


@pytest.mark.asyncio
async def test_malformed_output_retried_once():
    parser = IntentParser(FakeClient(["bad", '{"intent":"unknown","confidence":0.2}']), "Asia/Singapore")
    assert (await parser.parse("hello")).intent == IntentType.UNKNOWN


@pytest.mark.asyncio
async def test_two_malformed_outputs_fail_safely():
    parser = IntentParser(FakeClient(["bad", "also bad"]), "Asia/Singapore")
    with pytest.raises(IntentParseError):
        await parser.parse("hello")


@pytest.mark.asyncio
async def test_model_timeout_is_not_retried():
    client = FailingClient()
    parser = IntentParser(client, "Asia/Singapore")
    with pytest.raises(IntentParseError, match="timed out"):
        await parser.parse("remind me in 5 minutes")
    assert client.calls == 1


@pytest.mark.asyncio
async def test_calendar_update_preserves_details_not_changed_by_user():
    client = FakeClient([
        '{"intent":"propose_calendar_event","date_expression":"6 October","confidence":0.96}'
    ])
    parser = IntentParser(client, "Asia/Singapore")
    draft = ParsedIntent(
        intent=IntentType.PROPOSE_CALENDAR_EVENT,
        title="Dinner with Louis",
        date_expression="tomorrow",
        time="19:00",
        location=None,
        confidence=0.9,
    )

    updated = await parser.update(draft, "6th Oct")

    assert updated.title == "Dinner with Louis"
    assert updated.date_expression == "6 October"
    assert updated.time == "19:00"
    assert updated.location is None
