import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBE_ROOT = PROJECT_ROOT / "tests" / "sandbox" / "test_runtime" / "probe_dirs"


@contextmanager
def managed_test_dir(prefix: str):
    probe_dir = PROBE_ROOT / f"{prefix}{uuid.uuid4().hex}"
    probe_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield probe_dir
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
