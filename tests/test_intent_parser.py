import pytest

from app.intent_parser import IntentParseError, IntentParser
from app.models import IntentType


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def generate_json(self, system, prompt):
        return next(self.responses)


@pytest.mark.asyncio
async def test_valid_schema():
    parser = IntentParser(FakeClient(['{"intent":"create_reminder","title":"Pay Amex","date_expression":"tomorrow","time":"20:00","confidence":0.98}']), "Asia/Singapore")
    assert (await parser.parse("remind me")).intent == IntentType.CREATE_REMINDER


@pytest.mark.asyncio
async def test_malformed_output_retried_once():
    parser = IntentParser(FakeClient(["bad", '{"intent":"unknown","confidence":0.2}']), "Asia/Singapore")
    assert (await parser.parse("hello")).intent == IntentType.UNKNOWN


@pytest.mark.asyncio
async def test_two_malformed_outputs_fail_safely():
    parser = IntentParser(FakeClient(["bad", "also bad"]), "Asia/Singapore")
    with pytest.raises(IntentParseError):
        await parser.parse("hello")
