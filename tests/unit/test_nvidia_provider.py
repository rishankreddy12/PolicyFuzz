import pytest
import httpx
from pydantic import BaseModel

from policyfuzz.llm.nvidia_provider import NvidiaProvider, NVIDIA_DEFAULT_MODEL
from policyfuzz.llm.base import ProviderError, FatalProviderError
from policyfuzz.config import Settings, make_provider

class DummySchema(BaseModel):
    name: str

@pytest.mark.asyncio
async def test_nvidia_provider_success(monkeypatch):
    class MockResponse:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": '{"name":"test"}'}}]}
        def raise_for_status(self):
            pass

    class MockClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def post(self, url, json, headers):
            assert headers["Authorization"].startswith("Bearer nvapi-")
            assert "application/json" in headers["Accept"]
            return MockResponse()

    monkeypatch.setattr("httpx.AsyncClient", MockClient)

    provider = NvidiaProvider(api_key="nvapi-test1234", timeout=5)
    result = await provider.complete_json(
        model=NVIDIA_DEFAULT_MODEL,
        system="system prompt",
        user="user prompt",
        schema=DummySchema
    )
    assert result == '{"name":"test"}'

@pytest.mark.asyncio
async def test_nvidia_provider_missing_key():
    provider = NvidiaProvider(api_key="", timeout=5)
    with pytest.raises(FatalProviderError, match="NVIDIA_API_KEY is not set"):
        await provider.complete_json(model="test", system="", user="")

@pytest.mark.asyncio
async def test_nvidia_provider_unauthorized(monkeypatch):
    class MockResponse:
        status_code = 401

    class MockClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def post(self, url, json, headers):
            return MockResponse()

    monkeypatch.setattr("httpx.AsyncClient", MockClient)

    provider = NvidiaProvider(api_key="nvapi-invalid", timeout=5)
    with pytest.raises(FatalProviderError, match="HTTP 401 Unauthorized"):
        await provider.complete_json(model="test", system="", user="")

def test_make_provider_nvidia():
    settings = Settings(
        provider="nvidia",
        db_path="data/test.db",
        runs_dir="data/runs",
        ollama_host="http://localhost:11434",
        model_a="meta/llama-3.2-11b-vision-instruct",
        model_b="meta/llama-3.2-11b-vision-instruct",
        model_c="meta/llama-3.2-11b-vision-instruct",
        model_strong="meta/llama-3.2-11b-vision-instruct",
        nvidia_api_key="nvapi-test",
    )
    prov = make_provider(settings)
    assert prov.name == "nvidia"
    assert prov.api_key == "nvapi-test"
