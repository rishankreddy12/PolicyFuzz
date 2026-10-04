import json
import httpx
from typing import Type
from pydantic import BaseModel

from policyfuzz.llm.base import LLMProvider, ProviderError, FatalProviderError

class OllamaProvider:
    name = "ollama"
    
    def __init__(self, host: str, timeout: int):
        self.host = host.rstrip('/')
        self.timeout = timeout
        
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
        url = f"{self.host}/api/chat"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "stream": False,
            "format": schema.model_json_schema() if schema else "json",
            "options": {
                "temperature": temperature,
                "seed": 7
            }
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                
                if response.status_code == 404:
                    raise FatalProviderError(f"model {model} not installed; run: ollama pull {model}")
                    
                response.raise_for_status()
                data = response.json()
                return data["message"]["content"]
                
        except httpx.TimeoutException as e:
            raise ProviderError(f"Ollama request timed out after {self.timeout}s") from e
        except httpx.RequestError as e:
            raise ProviderError(f"Ollama connection error: {e}") from e
        except (KeyError, ValueError) as e:
            raise ProviderError(f"Invalid response format from Ollama: {e}") from e
