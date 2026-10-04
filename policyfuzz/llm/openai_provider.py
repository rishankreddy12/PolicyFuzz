import json
import httpx
import asyncio
from typing import Type
from pydantic import BaseModel

from policyfuzz.llm.base import LLMProvider, ProviderError, FatalProviderError

class OpenAIProvider:
    name = "openai"
    
    def __init__(self, host: str, timeout: int, api_key: str = "123456"):
        self.host = host.rstrip('/')
        self.timeout = timeout
        self.api_key = api_key
        
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
        model = kwargs.get("model", model)
        system = kwargs.get("system", system)
        user = kwargs.get("user", user)
        schema = kwargs.get("schema", schema)
        temperature = kwargs.get("temperature", temperature)
        url = f"{self.host}/chat/completions"
        
        # Instruct the model to return JSON explicitly
        schema_json = json.dumps(schema.model_json_schema()) if schema else "{}"
        augmented_system = f"{system}\n\nYou MUST reply ONLY with valid JSON matching this schema:\n{schema_json}"
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": augmented_system},
                {"role": "user", "content": user}
            ],
            "temperature": temperature,
            # Some Gemini proxies might crash if we pass response_format, but OpenAI format typically supports it. 
            # We'll leave it as json_object to encourage valid JSON.
            "response_format": {"type": "json_object"}
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    
                    if response.status_code == 404:
                        raise FatalProviderError(f"model {model} not found or endpoint incorrect.")
                        
                    response.raise_for_status()
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                    
            except FatalProviderError:
                raise
            except httpx.TimeoutException as e:
                if attempt == max_attempts:
                    raise ProviderError(f"OpenAI API request timed out after {self.timeout}s ({max_attempts} attempts)") from e
                await asyncio.sleep(1.0 * attempt)
            except httpx.RequestError as e:
                if attempt == max_attempts:
                    raise ProviderError(f"OpenAI API connection error after {max_attempts} attempts: {e}") from e
                await asyncio.sleep(1.0 * attempt)
            except (KeyError, ValueError, IndexError) as e:
                # Let's fallback and log it clearly
                err_text = getattr(e, 'response', None)
                err_msg = err_text.text if err_text else ""
                raise ProviderError(f"Invalid response format from OpenAI API: {e}\nRaw response: {err_msg}") from e
