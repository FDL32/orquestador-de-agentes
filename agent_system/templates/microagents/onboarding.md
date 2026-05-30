---
triggers: ["unknown repo", "new project", "bootstrap", "qué es este repo", "how to start"]
---

# Microagent: Onboarding a Repositorios Nuevos

Este microagent se activa cuando un agente detecta un repositorio desconocido o arranca un proyecto desde cero.

## 1. Contexto Canónico
Antes de analizar código o proponer arquitecturas, **siempre lee `PROJECT.md`** en la raíz del workspace. Este archivo contiene las reglas locales, el prefijo de tickets y la estructura del proyecto.
Para comprender la terminología del motor (ej. "EventBus", "Manager", "TP Check"), **siempre lee `.agent/glossary.md`**.

## 2. Detección de Tech Stack
Utiliza heurísticas básicas para entender la tecnología antes de invocar skills complejos:
- **Python:** Busca `pyproject.toml`, `requirements.txt` o `setup.py`.
- **Node/JS/TS:** Busca `package.json`, `tsconfig.json`.
- **Rust:** Busca `Cargo.toml`.
- **Go:** Busca `go.mod`.
- **Java/Kotlin:** Busca `pom.xml` o `build.gradle`.

## 3. Primeros Pasos
Si el proyecto está vacío:
1. Rellena el `PROJECT.md` usando la plantilla existente si aún dice `Ticket prefix: XXX`.
2. Genera la estructura base según el stack detectado.
3. Asegúrate de que los archivos de colaboración (en `.agent/collaboration/`) no sean modificados accidentalmente.

*Si tienes dudas, revisa `.agent/glossary.md` o pregunta al usuario.*
