import pytest
import os
import tempfile
import json
from policyfuzz.llm.scripted_provider import ScriptedProvider
from policyfuzz.llm.base import FatalProviderError
from pydantic import BaseModel

class DummySchema(BaseModel):
    value: int

@pytest.mark.asyncio
async def test_scripted_provider():
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        json.dump({"meta": {}, "responses": {"test_key": {"value": 100}}}, f)
        temp_path = f.name
        
    os.environ["POLICYFUZZ_SCRIPTED_PATH"] = temp_path
    
    try:
        provider = ScriptedProvider()
        
        # Valid key
        res = await provider.complete_json(
            role="role", call_key="test_key", system="sys", user="user", 
            schema=DummySchema, model="model"
        )
        assert json.loads(res)["value"] == 100
        
        # Missing key -> fatal error
        with pytest.raises(FatalProviderError):
            await provider.complete_json(
                role="role", call_key="missing", system="sys", user="user", 
                schema=DummySchema, model="model"
            )
            
    finally:
        os.unlink(temp_path)
        del os.environ["POLICYFUZZ_SCRIPTED_PATH"]
