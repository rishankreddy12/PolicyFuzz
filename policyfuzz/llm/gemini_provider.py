"""Native Google Gemini REST API provider for PolicyFuzz.

Uses the generativelanguage.googleapis.com/v1beta endpoint directly
via httpx, with JSON mode (responseMimeType=application/json) and
optional responseSchema for structured output.
"""

import json
import httpx
import asyncio
from typing import Type, Optional
from pydantic import BaseModel

from policyfuzz.llm.base import LLMProvider, ProviderError, FatalProviderError


def _pydantic_to_gemini_schema(schema_cls: Type[BaseModel]) -> dict:
    """Convert a Pydantic model's JSON schema to Gemini-compatible format.
    
    Gemini's responseSchema supports a subset of JSON Schema:
    type, properties, items, required, enum, description.
    We strip unsupported keys (title, default, $defs, anyOf, allOf, etc.)
    to avoid 400 errors.
    """
    raw = schema_cls.model_json_schema()
    
    def _clean(node: dict) -> dict:
        """Recursively strip keys Gemini doesn't understand."""
        out = {}
        
        # Resolve $ref / $defs (Pydantic v2 uses these for nested models)
        defs = raw.get("$defs", {})
        
        if "$ref" in node:
            ref_name = node["$ref"].rsplit("/", 1)[-1]
            if ref_name in defs:
                return _clean(defs[ref_name])
            return {"type": "object"}
        
        # Handle anyOf (Optional fields in Pydantic v2)
        if "anyOf" in node:
            # Pick the first non-null type
            for variant in node["anyOf"]:
                if variant.get("type") != "null":
                    return _clean(variant)
            return {"type": "string"}
        
        # Copy supported keys
        for key in ("type", "description", "enum"):
            if key in node:
                out[key] = node[key]
        
        if "properties" in node:
            out["type"] = "object"
            out["properties"] = {
                k: _clean(v) for k, v in node["properties"].items()
            }
        
        if "required" in node:
            out["required"] = node["required"]
        
        if "items" in node:
            out["items"] = _clean(node["items"])
            out["type"] = "array"
        
        # Default to string if no type resolved
        if "type" not in out:
            out["type"] = "string"
            
        return out
    
    return _clean(raw)


class GeminiProvider:
    """Calls Google Gemini REST API natively with JSON structured output."""
    
    name = "gemini"
    
    GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
    
    def __init__(self, api_key: str, timeout: int = 180, model: str = "gemini-3.5-flash"):
        self.api_key = api_key
        self.timeout = timeout
        self.default_model = model
    
    async def complete_json(
        self,
        model: str = None,
        system: str = "",
        user: str = "",
        schema: Type[BaseModel] = None,
        temperature: float = 0.0,
        *,
        role: str = "",
        call_key: str = "",
        **kwargs
    ) -> str:
        """Send a structured JSON request to Gemini's generateContent endpoint."""
        primary_model = kwargs.get("model", model) or self.default_model
        system = kwargs.get("system", system)
        user = kwargs.get("user", user)
        schema = kwargs.get("schema", schema)
        temperature = kwargs.get("temperature", temperature)
        
        # Candidate models to try in order (primary, then fallback)
        model_candidates = [primary_model]
        if primary_model != "gemini-3.5-flash":
            model_candidates.append("gemini-3.5-flash")
        if "gemini-3.5-flash-lite" not in model_candidates:
            model_candidates.append("gemini-3.5-flash-lite")
            
        last_error = None
        for current_model in model_candidates:
            url = f"{self.GEMINI_BASE}/models/{current_model}:generateContent?key={self.api_key}"
            
            # Build the request payload
            payload = {
                "contents": [
                    {
                        "parts": [{"text": user}]
                    }
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "responseMimeType": "application/json",
                }
            }
            
            # Add system instruction if provided
            if system:
                payload["systemInstruction"] = {
                    "parts": [{"text": system}]
                }
            
            # Add response schema for structured output if a Pydantic model is provided
            if schema:
                schema_json = json.dumps(schema.model_json_schema())
                schema_hint = f"\n\nYou MUST reply ONLY with valid JSON matching this schema:\n{schema_json}"
                if system:
                    payload["systemInstruction"]["parts"][0]["text"] += schema_hint
                else:
                    payload["systemInstruction"] = {
                        "parts": [{"text": f"Reply ONLY with valid JSON matching this schema:\n{schema_json}"}]
                    }
                
                try:
                    gemini_schema = _pydantic_to_gemini_schema(schema)
                    payload["generationConfig"]["responseSchema"] = gemini_schema
                except Exception:
                    pass
            
            headers = {"Content-Type": "application/json"}
            max_attempts = 3
            
            for attempt in range(1, max_attempts + 1):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        response = await client.post(url, json=payload, headers=headers)
                        
                        if response.status_code == 400:
                            # If schema was rejected by Gemini, try once without responseSchema
                            if "responseSchema" in payload.get("generationConfig", {}):
                                del payload["generationConfig"]["responseSchema"]
                                retry_resp = await client.post(url, json=payload, headers=headers)
                                if retry_resp.status_code == 200:
                                    data = retry_resp.json()
                                    return data["candidates"][0]["content"]["parts"][0]["text"]
                            error_body = response.text
                            raise FatalProviderError(
                                f"Gemini API 400 Bad Request for model '{current_model}': {error_body}"
                            )
                        
                        if response.status_code == 403:
                            raise FatalProviderError(
                                f"Gemini API 403 Forbidden — check your API key permissions."
                            )
                        
                        if response.status_code == 404:
                            # Model not found or deprecated, try next model candidate
                            break
                        
                        if response.status_code in (429, 500, 503):
                            if attempt == max_attempts:
                                # Fall through to next candidate model
                                last_error = f"Gemini API {response.status_code} on {current_model}: {response.text[:200]}"
                                break
                            wait = min(2.0 * (2 ** (attempt - 1)), 10)
                            await asyncio.sleep(wait)
                            continue
                        
                        response.raise_for_status()
                        data = response.json()
                        
                        candidates = data.get("candidates", [])
                        if not candidates:
                            raise ProviderError(f"Gemini returned empty candidates: {data}")
                        return candidates[0]["content"]["parts"][0]["text"]
                        
                except FatalProviderError:
                    raise
                except httpx.TimeoutException as e:
                    if attempt == max_attempts:
                        last_error = f"Gemini timeout on {current_model}: {e}"
                        break
                    await asyncio.sleep(2.0)
                except httpx.RequestError as e:
                    if attempt == max_attempts:
                        last_error = f"Gemini request error on {current_model}: {e}"
                        break
                    await asyncio.sleep(2.0)
                    
        raise ProviderError(f"All Gemini model candidates failed. Last error: {last_error}")

