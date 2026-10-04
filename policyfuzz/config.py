"""Settings dataclass and constants for PolicyFuzz."""

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (walk up from this file)
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env", override=False)


# Constants
TARGET_CASES = 30
MIN_CASES = 24
MAX_CASES = 36
MAX_POLICY_BYTES = 20480
MAX_RETRIES = 2
CALL_TIMEOUT_S = 180
PANEL_CONCURRENCY = 2
MAX_PATCH_ROUNDS = 2
MAX_EDITS = 6
SUCCESS_REDUCTION = 0.5
MIN_CONFORMANCE = 0.8


@dataclass
class Settings:
    provider: str
    db_path: str
    runs_dir: str
    ollama_host: str
    model_a: str
    model_b: str
    model_c: str
    model_strong: str
    openai_host: str = ""
    openai_key: str = ""
    gemini_api_key: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        provider = os.getenv("POLICYFUZZ_PROVIDER", "scripted")
        db_path = os.getenv("POLICYFUZZ_DB", "data/policyfuzz.db")
        runs_dir = os.getenv("POLICYFUZZ_RUNS_DIR", "data/runs")
        
        # Create data directories lazily
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(runs_dir).mkdir(parents=True, exist_ok=True)
        
        return cls(
            provider=provider,
            db_path=db_path,
            runs_dir=runs_dir,
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            openai_host=os.getenv("OPENAI_HOST", "http://127.0.0.1:8317/v1"),
            openai_key=os.getenv("OPENAI_KEY", "123456"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            model_a=os.getenv("POLICYFUZZ_MODEL_A", "gemini-pro-agent"),
            model_b=os.getenv("POLICYFUZZ_MODEL_B", "gemini-pro-agent"),
            model_c=os.getenv("POLICYFUZZ_MODEL_C", "gemini-pro-agent"),
            model_strong=os.getenv("POLICYFUZZ_MODEL_STRONG", "gemini-pro-agent"),
        )

def make_provider(settings: Settings):
    if settings.provider == "gemini":
        from policyfuzz.llm.gemini_provider import GeminiProvider
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            timeout=CALL_TIMEOUT_S,
            model=settings.model_strong or "gemini-3.5-flash"
        )
    elif settings.provider == "ollama":
        from policyfuzz.llm.ollama_provider import OllamaProvider
        return OllamaProvider(settings.ollama_host, CALL_TIMEOUT_S)
    elif settings.provider == "openai":
        from policyfuzz.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(settings.openai_host, CALL_TIMEOUT_S, settings.openai_key)
    else:
        from policyfuzz.llm.scripted_provider import ScriptedProvider
        return ScriptedProvider()
