# Legacy alias: review_manager.md

> **Renombrado (WOT-2026-008e).** Este prompt se llama ahora
> `prompts/manager_review.md` (regla actor-first de DEC-008D-001:
> `manager_review`, no `review_manager`).

Fuente canonica:
- `prompts/manager_review.md`

No editar este archivo salvo para mantener el alias de compatibilidad.
El contrato operativo vive solo en `manager_review.md`; aqui no se duplica
para evitar drift entre dos copias. La tolerancia de este stub por
`scripts/discover_skills.py --check-naming` proviene del frontmatter
`legacy_aliases: [review_manager]` declarado en el canonico, no de una
excepcion hardcodeada.
