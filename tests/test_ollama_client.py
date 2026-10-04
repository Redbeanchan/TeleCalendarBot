import pytest

from app.ollama_client import OllamaClient


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": '{"intent":"unknown"}'}}


class FakeAsyncClient:
    payload = None

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, json):
        self.__class__.payload = json
        return FakeResponse()


@pytest.mark.asyncio
async def test_resource_limits_and_thinking_are_sent(monkeypatch):
    monkeypatch.setattr("app.ollama_client.httpx.AsyncClient", FakeAsyncClient)
    client = OllamaClient("http://ollama", "qwen3:4b", num_threads=6, num_ctx=1024, num_gpu=0)

    await client.generate_json("system", "message", {"type": "object"})

    assert FakeAsyncClient.payload["think"] is False
    assert FakeAsyncClient.payload["format"] == {"type": "object"}
    assert FakeAsyncClient.payload["options"] == {
        "temperature": 0,
        "num_predict": 128,
        "num_thread": 6,
        "num_ctx": 1024,
        "num_gpu": 0,
    }


@pytest.mark.asyncio
async def test_gpu_override_is_omitted_for_automatic_selection(monkeypatch):
    monkeypatch.setattr("app.ollama_client.httpx.AsyncClient", FakeAsyncClient)
    client = OllamaClient("http://127.0.0.1:11434", "qwen3:14b", num_gpu=-1)

    await client.generate_json("system", "message")

    assert "num_gpu" not in FakeAsyncClient.payload["options"]
