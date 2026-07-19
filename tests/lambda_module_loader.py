"""Load same-named Lambda entry points without polluting sys.modules as index."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
COMMON_PYTHON = ROOT / "lambda" / "common" / "python"


def load_lambda_module(unique_name: str, relative_path: str) -> ModuleType:
    source_path = ROOT / relative_path
    for import_path in (COMMON_PYTHON, source_path.parent, source_path.parent / "python"):
        path_text = str(import_path)
        if import_path.exists() and path_text not in sys.path:
            sys.path.insert(0, path_text)
    spec = importlib.util.spec_from_file_location(unique_name, source_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {source_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module
