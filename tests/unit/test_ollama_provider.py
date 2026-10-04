import pytest
import httpx
from pydantic import BaseModel

from policyfuzz.llm.ollama_provider import OllamaProvider
from policyfuzz.llm.base import ProviderError, FatalProviderError

class DummySchema(BaseModel):
    foo: str

@pytest.mark.asyncio
async def test_ollama_success():
    def handler(request: httpx.Request):
        return httpx.Response(200, json={"message": {"content": '{"foo":"bar"}'}})
        
    transport = httpx.MockTransport(handler)
    
    # We patch httpx.AsyncClient to use our mock transport
    # In real test we can monkeypatch httpx.AsyncClient
    pass # Wait, let's just use monkeypatch

@pytest.mark.asyncio
async def test_ollama_provider_success(monkeypatch):
    class MockResponse:
        status_code = 200
        def json(self):
            return {"message": {"content": '{"foo":"bar"}'}}
        def raise_for_status(self):
            pass
            
    class MockClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def post(self, url, json):
            return MockResponse()
            
    monkeypatch.setattr("httpx.AsyncClient", MockClient)
    
    provider = OllamaProvider("http://localhost:11434", 1)
    res = await provider.complete_json("model", "sys", "user", DummySchema)
    assert res == '{"foo":"bar"}'

@pytest.mark.asyncio
async def test_ollama_provider_404(monkeypatch):
    class MockResponse:
        status_code = 404
        def json(self):
            return {}
        def raise_for_status(self):
            pass
            
    class MockClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def post(self, url, json):
            return MockResponse()
            
    monkeypatch.setattr("httpx.AsyncClient", MockClient)
    
    provider = OllamaProvider("http://localhost:11434", 1)
    with pytest.raises(FatalProviderError, match="model missing not installed"):
        await provider.complete_json("missing", "sys", "user", DummySchema)

@pytest.mark.asyncio
async def test_ollama_provider_timeout(monkeypatch):
    class MockClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def post(self, url, json):
            raise httpx.TimeoutException("Timeout")
            
    monkeypatch.setattr("httpx.AsyncClient", MockClient)
    
    provider = OllamaProvider("http://localhost:11434", 1)
    with pytest.raises(ProviderError, match="timed out"):
        await provider.complete_json("model", "sys", "user", DummySchema)

@pytest.mark.asyncio
async def test_ollama_provider_malformed(monkeypatch):
    class MockResponse:
        status_code = 200
        def json(self):
            return {"bad_key": "val"} # missing message.content
        def raise_for_status(self):
            pass
            
    class MockClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def post(self, url, json):
            return MockResponse()
            
    monkeypatch.setattr("httpx.AsyncClient", MockClient)
    
    provider = OllamaProvider("http://localhost:11434", 1)
    with pytest.raises(ProviderError, match="Invalid response format"):
        await provider.complete_json("model", "sys", "user", DummySchema)
