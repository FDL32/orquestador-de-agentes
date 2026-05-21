# .gitignore Completo

# ============================================
# SEGURIDAD - SECRETOS Y CREDENCIALES
# ============================================
privada/
.env
.env.*
*.pem
*.key
*.p12
config.json
credentials.json
sender_config.json
remitente.json

# ============================================
# PYTHON Y ENTORNO
# ============================================
__pycache__/
*.py[cod]
*$py.class
*.so
.venv/
venv/
.Python
*.egg-info/
dist/
build/

# ============================================
# CARPETAS DE SALIDA (con .gitkeep)
# ============================================
/output/*
!/output/.gitkeep
/logs/*
!/logs/.gitkeep
/backups/*
!/backups/.gitkeep
/data/*.json
!data/.gitkeep

# ============================================
# TESTS Y CACHE
# ============================================
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/

# ============================================
# IDE Y SISTEMA
# ============================================
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store
Thumbs.db
