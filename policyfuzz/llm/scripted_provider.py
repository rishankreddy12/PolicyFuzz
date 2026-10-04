"""Scripted LLM provider for deterministic offline execution."""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel

from policyfuzz.llm.base import LLMProvider, FatalProviderError

class ScriptedProvider(LLMProvider):
    name = "scripted"
    
    def __init__(self):
        self.responses: Dict[str, Any] = {}
        self._load_fixtures()
        
    def _load_fixtures(self) -> None:
        # Check env var for path, default to fixtures/demo/scripted_responses.json
        path_str = os.getenv("POLICYFUZZ_SCRIPTED_PATH")
        if not path_str:
            base_dir = Path(__file__).parent.parent.parent
            path_str = str(base_dir / "fixtures" / "demo" / "scripted_responses.json")
            
        path = Path(path_str)
        if not path.exists():
            return # We might be running tests or regenerating them
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.responses = data.get("responses", {})
        except Exception as e:
            raise FatalProviderError(f"Failed to load scripted responses from {path_str}: {e}")

    async def complete_json(
        self,
        *,
        role: str,
        call_key: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: Optional[str],
        temperature: float = 0.0
    ) -> str:
        if call_key not in self.responses:
            raise FatalProviderError(f"no scripted response for {call_key}")
            
        return json.dumps(self.responses[call_key])
