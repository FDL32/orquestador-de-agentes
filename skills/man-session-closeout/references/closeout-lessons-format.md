# closeout_lessons.md Format

`closeout_lessons.md` is a bridge file for the next planning cycle.

## Sections

### Summary

- Ticket closed
- Main learnings
- Scope split
- Outstanding follow-ups

### Scope

- `local`: lecciones que se quedan en el proyecto destino
- `generalizable`: lecciones que pueden subir al motor
- `dudoso`: lecciones pendientes con TTL de 3 WPs

### Actions for next planning cycle

- `man-create-work-plan` reads this file before creating the next plan
- The file should include only durable lessons, not raw logs
- Prefer short, direct bullets

## Example

```markdown
# Closeout Lessons - WP-2026-163

## Summary
- The agent proposed three learnings; the user accepted two and deferred one.
- A `dudoso` item was left with `ttl_wps: 3`.

## Scope
- learning 1: generalizable
- learning 2: local
- learning 3: dudoso

## Actions for next planning cycle
- Start with the accepted generalizable learnings.
- Recheck the deferred item if it still appears relevant.
- Keep the plan-checklist aligned with the latest gate rules.
```
