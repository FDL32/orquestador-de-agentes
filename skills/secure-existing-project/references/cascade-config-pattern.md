# Patrón de Configuración en Cascada

## config.py

```python
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
PRIVATE_DIR = ROOT_DIR.parent.parent / "privada"

DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
LOGS_DIR = ROOT_DIR / "logs"

for d in [OUTPUT_DIR, LOGS_DIR]:
    d.mkdir(exist_ok=True)
```

## settings.py

```python
import json
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
from .config import PRIVATE_DIR, ROOT_DIR

def _load_env():
    if env_path := os.getenv("PROJECT_ENV_FILE"):
        load_dotenv(Path(env_path))
    elif (PRIVATE_DIR / ".env").exists():
        load_dotenv(PRIVATE_DIR / ".env")
    elif (ROOT_DIR / ".env").exists():
        load_dotenv(ROOT_DIR / ".env")

def get_config_file(filename: str) -> Path:
    name = Path(filename).name
    if (private := PRIVATE_DIR / name).exists():
        return private
    if (project := ROOT_DIR / filename).exists():
        return project
    if (example := ROOT_DIR / f"{filename}.example").exists():
        return example
    return ROOT_DIR / filename

def load_json_config(filename: str) -> dict:
    path = get_config_file(filename)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

_load_env()

@dataclass(frozen=True)
class Settings:
    API_KEY: str = os.getenv("API_KEY", "")
    API_SECRET: str = os.getenv("API_SECRET", "")
```

## Uso

```python
from src.config import DATA_DIR, OUTPUT_DIR
from src.settings import Settings, load_json_config

settings = Settings()
config = load_json_config("data/config.json")
```
