"""Structured LLM calling with schema validation and retries."""

import sqlite3
import json
import time
from typing import Type, TypeVar, Callable, Optional, List
from pydantic import BaseModel, ValidationError

from policyfuzz import db
from policyfuzz.llm.base import LLMProvider, ProviderError, FatalProviderError

T = TypeVar("T", bound=BaseModel)

class StructuredOutputError(Exception):
    """Raised when structured generation fails after all retries."""
    def __init__(self, call_key: str, last_error: str):
        super().__init__(f"Call {call_key} failed: {last_error}")
        self.call_key = call_key
        self.last_error = last_error

def _extract_json(text: str) -> str:
    """Strip markdown fences or extra text to find the JSON block."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[len("```json"):]
    elif text.startswith("```"):
        text = text[len("```"):]
    
    if text.endswith("```"):
        text = text[:-3]
    
    # Try to find the first '{' or '[' if there is leading text
    start_idx = -1
    for i, c in enumerate(text):
        if c in ('{', '['):
            start_idx = i
            break
            
    if start_idx != -1:
        # Find the last '}' or ']'
        end_idx = -1
        for i in range(len(text)-1, -1, -1):
            if text[i] in ('}', ']'):
                end_idx = i
                break
        if end_idx != -1 and end_idx >= start_idx:
            text = text[start_idx:end_idx+1]
            
    return text.strip()

async def structured_call(
    provider: LLMProvider,
    conn: sqlite3.Connection,
    run_id: str,
    role: str,
    call_key: str,
    system: str,
    user: str,
    schema: Type[T],
    model: Optional[str],
    validator: Optional[Callable[[T], List[str]]] = None,
    max_retries: int = 2
) -> T:
    """Call the LLM, validate against the Pydantic schema and optional semantic validator, with retries."""
    attempts = max_retries + 1
    last_error_str = ""
    current_user = user
    
    request_dict = {"system": system, "user": user, "schema": schema.__name__}
    
    for attempt in range(1, attempts + 1):
        start_t = time.time()
        parsed_ok = False
        error_msg = None
        raw_response = ""
        
        try:
            raw_response = await provider.complete_json(
                role=role,
                call_key=call_key,
                system=system,
                user=current_user,
                schema=schema,
                model=model
            )
            
            clean_json = _extract_json(raw_response)
            
            # Validate JSON and Schema
            try:
                parsed_obj = schema.model_validate_json(clean_json)
            except ValidationError as ve:
                errors = []
                for err in ve.errors():
                    loc = ".".join(str(l) for l in err["loc"])
                    errors.append(f"{loc}: {err['msg']}")
                raise ValueError("Schema validation failed: " + "; ".join(errors))
            except json.JSONDecodeError as je:
                raise ValueError(f"Invalid JSON: {je}")

            # Semantic validation
            if validator:
                semantic_errors = validator(parsed_obj)
                if semantic_errors:
                    raise ValueError("Semantic validation failed: " + "; ".join(semantic_errors))
                    
            parsed_ok = True
            
            # Log successful call
            latency_ms = int((time.time() - start_t) * 1000)
            request_dict["user"] = current_user
            db.log_llm_call(conn, run_id, call_key, role, provider.name, model or "none", attempt, json.dumps(request_dict), raw_response, parsed_ok, None, latency_ms)
            
            return parsed_obj
            
        except FatalProviderError as fpe:
            error_msg = f"Fatal Provider Error: {str(fpe)}"
            latency_ms = int((time.time() - start_t) * 1000)
            request_dict["user"] = current_user
            db.log_llm_call(conn, run_id, call_key, role, provider.name, model or "none", attempt, json.dumps(request_dict), raw_response, False, error_msg, latency_ms)
            raise
        except (ProviderError, ValueError) as e:
            last_error_str = str(e)
            error_msg = last_error_str
            latency_ms = int((time.time() - start_t) * 1000)
            request_dict["user"] = current_user
            db.log_llm_call(conn, run_id, call_key, role, provider.name, model or "none", attempt, json.dumps(request_dict), raw_response, False, error_msg, latency_ms)
            
            # Add feedback for next attempt
            current_user = f"{user}\n\nYour previous output was rejected: {last_error_str}. Return ONLY valid JSON matching the schema."
            
    # Exhausted
    raise StructuredOutputError(call_key, last_error_str)
