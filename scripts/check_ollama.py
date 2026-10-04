import sys
import httpx
from policyfuzz.config import Settings

def main():
    settings = Settings.from_env()
    host = settings.ollama_host.rstrip('/')
    
    required_models = {
        settings.model_a,
        settings.model_b,
        settings.model_c,
        settings.model_strong
    }
    
    try:
        response = httpx.get(f"{host}/api/tags", timeout=5.0)
        response.raise_for_status()
        data = response.json()
        installed_models = {m["name"] for m in data.get("models", [])}
    except Exception as e:
        print(f"Error connecting to Ollama at {host}: {e}")
        sys.exit(1)
        
    missing = required_models - installed_models
    
    print("Ollama Model Check:")
    print("-" * 40)
    for req in required_models:
        if req in installed_models:
            print(f"✅ {req} (installed)")
        else:
            print(f"❌ {req} (missing)")
            
    if missing:
        print("\nMissing models detected. Run the following commands to install them:")
        for m in missing:
            print(f"  ollama pull {m}")
        sys.exit(1)
    else:
        print("\nAll required models are installed.")
        sys.exit(0)

if __name__ == "__main__":
    main()
