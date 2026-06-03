# Checklist de Seguridad

## Auditoría Inicial

### Buscar Secrets en Código
```bash
# API Keys
grep -rE "(api_key|apikey|API_KEY)" src/ --include="*.py"

# Contraseñas
grep -rE "(password|PASSWORD|passwd|pwd)" src/ --include="*.py"

# Tokens
grep -rE "(token|TOKEN|auth_token)" src/ --include="*.py"

# Secrets
grep -rE "(secret|SECRET|client_secret)" src/ --include="*.py"

# Strings de conexión
grep -rE "(connection_string|DATABASE_URL)" src/ --include="*.py"
```

### Archivos a Verificar
- [ ] `.env` en raíz
- [ ] `config.json`
- [ ] `credentials.json`
- [ ] `settings.json`
- [ ] `*.key`, `*.pem`
- [ ] `debug_*.py` (scripts de prueba)

### Extensiones Sensibles
```bash
find . -name "*.env" -o -name "*.key" -o -name "*.pem" \
       -o -name "credentials*" -o -name "config.json"
```

## Post-Migración

### Verificar .gitignore
```gitignore
privada/
.env
.env.*
*.key
*.pem
config.json
credentials.json
```

### Verificar Estructura
```bash
# privada/ NO debe estar en git
git check-ignore privada/

# .env.example DEBE existir
test -f publica/repo/.env.example && echo "OK"
```

### Verificar Código
- [ ] No hay strings de conexión hardcodeadas
- [ ] Variables de entorno usadas vía `settings.py`
- [ ] No hay `print()` de datos sensibles
- [ ] Logging sin datos personales
