# Template pyproject.toml

```toml
[project]
name = "mi-proyecto"
version = "0.1.0"
description = "DescripciÃ³n del proyecto"
requires-python = ">=3.10"
dependencies = [
    "loguru>=0.7.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=4.0.0",
    "ruff>=0.4.0",
    "mypy>=1.0.0",
]

[tool.ruff]
line-length = 120
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "N"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
```
