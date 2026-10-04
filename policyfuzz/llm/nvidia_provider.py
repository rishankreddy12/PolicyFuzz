"""NVIDIA NIM / Cloud Functions LLM Provider for PolicyFuzz.

Uses NVIDIA's OpenAI-compatible API endpoint (https://integrate.api.nvidia.com/v1)
with bearer token authentication and JSON response enforcement.
"""

import json
import httpx
import asyncio
from typing import Type, Optional
from pydantic import BaseModel

from policyfuzz.llm.base import LLMProvider, ProviderError, FatalProviderError

NVIDIA_DEFAULT_HOST = "https://integrate.api.nvidia.com/v1"
NVIDIA_DEFAULT_MODEL = "meta/llama-3.2-11b-vision-instruct"


class NvidiaProvider:
    name = "nvidia"

    def __init__(
        self,
        api_key: str,
        timeout: int = 180,
        host: str = NVIDIA_DEFAULT_HOST,
        model: str = NVIDIA_DEFAULT_MODEL,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.host = host.rstrip("/")
        self.default_model = model or NVIDIA_DEFAULT_MODEL

    async def complete_json(
        self,
        model: Optional[str] = None,
        system: str = "",
        user: str = "",
        schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0,
        *,
        role: str = "",
        call_key: str = "",
        **kwargs,
    ) -> str:
        chosen_model = model or kwargs.get("model") or self.default_model
        system_text = kwargs.get("system", system)
        user_text = kwargs.get("user", user)
        schema_cls = kwargs.get("schema", schema)
        temp = kwargs.get("temperature", temperature)

        if not self.api_key:
            raise FatalProviderError(
                "NVIDIA_API_KEY is not set. Please provide your NVIDIA API key (e.g. nvapi-...) in .env or Settings."
            )

        url = f"{self.host}/chat/completions"

        # Construct prompt enforcing JSON conforming to schema
        schema_json = json.dumps(schema_cls.model_json_schema()) if schema_cls else "{}"
        augmented_system = (
            f"{system_text}\n\n"
            f"You MUST reply ONLY with a valid JSON instance conforming to this JSON Schema:\n{schema_json}\n"
            "Return the actual data instance fulfilling the fields, NOT the schema definition. Do not output markdown fences or explanatory text."
        )

        payload = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": augmented_system},
                {"role": "user", "content": user_text},
            ],
            "temperature": temp,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)

                    if response.status_code == 401:
                        raise FatalProviderError(
                            "NVIDIA API key rejected (HTTP 401 Unauthorized). Please check your key."
                        )

                    if response.status_code == 404:
                        raise FatalProviderError(
                            f"Model '{chosen_model}' not found on NVIDIA NIM (HTTP 404)."
                        )

                    if response.status_code == 429:
                        if attempt == max_attempts:
                            raise ProviderError("NVIDIA API rate limit exceeded (HTTP 429).")
                        await asyncio.sleep(2.0 * attempt)
                        continue

                    response.raise_for_status()
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    return content

            except FatalProviderError:
                raise
            except httpx.TimeoutException as e:
                if attempt == max_attempts:
                    raise ProviderError(
                        f"NVIDIA API request timed out after {self.timeout}s ({max_attempts} attempts)"
                    ) from e
                await asyncio.sleep(1.0 * attempt)
            except httpx.RequestError as e:
                if attempt == max_attempts:
                    raise ProviderError(
                        f"NVIDIA API connection error after {max_attempts} attempts: {e}"
                    ) from e
                await asyncio.sleep(1.0 * attempt)
            except (KeyError, ValueError, IndexError) as e:
                raise ProviderError(f"Invalid response format from NVIDIA API: {e}") from e

        raise ProviderError(f"NVIDIA API call failed after {max_attempts} attempts.")
