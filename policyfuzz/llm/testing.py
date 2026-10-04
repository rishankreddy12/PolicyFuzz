"""Testing utilities for LLM layer."""

import json
from typing import Optional, Dict, List
from pydantic import BaseModel

from policyfuzz.llm.base import LLMProvider, ProviderError

class FlakyProvider(LLMProvider):
    name = "flaky"
    
    def __init__(self, inner: LLMProvider, plan: Dict[str, List[str]]):
        """
        plan: dict of call_key -> list of instructions per attempt
        e.g. {"key1": ["malformed", "timeout", "ok"]}
        """
        self.inner = inner
        self.plan = plan
        self.attempts: Dict[str, int] = {}
        
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
        attempt_idx = self.attempts.get(call_key, 0)
        self.attempts[call_key] = attempt_idx + 1
        
        plan_for_key = self.plan.get(call_key, ["ok"])
        
        # If we exhausted the plan, repeat the last instruction
        instruction = plan_for_key[attempt_idx] if attempt_idx < len(plan_for_key) else plan_for_key[-1]
        
        if instruction == "malformed":
            return "{ unclosed json... "
        elif instruction == "timeout":
            raise ProviderError("simulated timeout")
        elif instruction == "invalid_schema":
            # Just return something valid JSON but wrong schema (empty dict usually fails required fields)
            return "{}"
        elif instruction == "ok":
            return await self.inner.complete_json(
                role=role, call_key=call_key, system=system, user=user,
                schema=schema, model=model, temperature=temperature
            )
        else:
            raise ValueError(f"Unknown flaky instruction: {instruction}")
