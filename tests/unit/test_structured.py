import pytest
from pydantic import BaseModel
import json

from policyfuzz import db
from policyfuzz.llm.base import FatalProviderError
from policyfuzz.llm.structured import structured_call, StructuredOutputError
from policyfuzz.llm.testing import FlakyProvider

class DummySchema(BaseModel):
    value: int

class DummyProvider:
    name = "dummy"
    async def complete_json(self, **kwargs) -> str:
        return '```json\n{"value": 42}\n```'

@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    yield c
    c.close()

@pytest.mark.asyncio
async def test_structured_call_success(conn):
    provider = DummyProvider()
    res = await structured_call(
        provider, conn, "run1", "role", "key1", "sys", "user", DummySchema, "model"
    )
    assert res.value == 42
    
    # Check db
    calls = db.list_llm_calls(conn, "run1")
    assert len(calls) == 1
    assert calls[0]['parsed_ok'] == 1

@pytest.mark.asyncio
async def test_structured_call_retry_feedback(conn):
    plan = {"key1": ["malformed", "ok"]}
    provider = FlakyProvider(DummyProvider(), plan)
    
    res = await structured_call(
        provider, conn, "run1", "role", "key1", "sys", "user", DummySchema, "model"
    )
    assert res.value == 42
    
    calls = db.list_llm_calls(conn, "run1")
    assert len(calls) == 2
    assert calls[0]['parsed_ok'] == 0
    assert calls[1]['parsed_ok'] == 1
    
    # Feedback should be in the request_json of the second call
    req2 = json.loads(calls[1]['request_json'])
    assert "Your previous output was rejected" in req2['user']

@pytest.mark.asyncio
async def test_structured_call_exhausted(conn):
    plan = {"key1": ["malformed", "malformed", "malformed", "malformed"]}
    provider = FlakyProvider(DummyProvider(), plan)
    
    with pytest.raises(StructuredOutputError):
        await structured_call(
            provider, conn, "run1", "role", "key1", "sys", "user", DummySchema, "model", max_retries=2
        )
        
    calls = db.list_llm_calls(conn, "run1")
    assert len(calls) == 3  # 1 initial + 2 retries

@pytest.mark.asyncio
async def test_structured_call_fatal_error(conn):
    class FatalDummy:
        name = "fatal"
        async def complete_json(self, **kwargs) -> str:
            raise FatalProviderError("no key")
            
    with pytest.raises(FatalProviderError):
        await structured_call(
            FatalDummy(), conn, "run1", "role", "key1", "sys", "user", DummySchema, "model"
        )
        
    calls = db.list_llm_calls(conn, "run1")
    assert len(calls) == 1
    assert calls[0]['parsed_ok'] == 0
    assert "Fatal Provider Error" in calls[0]['error']
