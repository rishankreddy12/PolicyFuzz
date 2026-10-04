"""Base classes and protocols for LLM providers."""

from typing import Protocol, Optional
from pydantic import BaseModel

class ProviderError(Exception):
    """Retryable error (timeout, 5xx, empty body, etc.)."""
    pass

class FatalProviderError(ProviderError):
    """Non-retryable error (missing scripted key, 4xx, etc.)."""
    pass

class LLMProvider(Protocol):
    name: str

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
        """Return raw JSON text conforming to the schema."""
        ...
