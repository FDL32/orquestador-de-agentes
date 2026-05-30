# WP -> WT Inventory (WT-2026-181 Fase 0)

> Generated: 2026-05-30
> Search method: Select-String over *.py, *.ps1, *.psm1, *.md (excluding .venv, .git, tests/sandbox, review_packets, tmp, uv-cache)

## Category A: Regex/Parsing patterns → must become dual `(?:WP|WT)-`

### bus/supervisor.py (10 regex locations)
| Line | Pattern | Type |
|------|---------|------|
| 439 | `r"WP-\d{4}-[A-Za-z0-9]+"` | Ticket extraction from work_plan |
| 442 | `r"WP-(\d{4})-([A-Za-z0-9]+)"` | Prefix parsing |
| 447 | `r"WP-\d{4}-(\d+)"` | Last number extraction |
| 448 | `r"WP-\d{4}-(\d+)"` | Existence check |
| 603 | `r"WP-(\d{4})-(\d+)"` | _next_ticket_id validator |
| 623-626 | `r"WP-\d{4}-[A-Za-z0-9]+"` (×4) | TURN.md table patterns |
| 632 | `r"(WP-\d{4}-[A-Za-z0-9]+)"` | Loose fallback in TURN.md |
| 639-641 | `r"WP-\d{4}-[A-Za-z0-9]+"` (×3) | work_plan.md patterns |
| 647 | `r"(WP-\d{4}-[A-Za-z0-9]+)"` | Loose fallback in work_plan.md |
| 661-663 | `r"WP-\d{4}-[A-Za-z0-9]+"` (×3) | _work_plan_active_ticket |
| 669 | `r"(WP-\d{4}-[A-Za-z0-9]+)"` | Loose fallback in _work_plan_active_ticket |
| 690 | `r"WP-(\d{4})-([A-Za-z0-9]+)"` | _ticket_sort_key validator |

### bus/review_bridge.py (3 regex locations)
| Line | Pattern | Type |
|------|---------|------|
| 114 | `r"\*\*ID:\*\*\s*(WP-\d{4}-\d+)"` | _get_active_ticket_id (1st occurrence) |
| 400 | `r"\*\*ID:\*\*\s*(WP-\d{4}-\d+)"` | _get_active_ticket_id (2nd occurrence, duplicate class) |
| 439 | `rf"...(?=\n### WP-|\Z)"` | Section boundary in _extract_ticket_section |

### scripts/validate_ticket_prose.py (6 locations)
| Line | Pattern | Type |
|------|---------|------|
| 456 | `"AUDIT_WP-*.md"` glob | Audit file detection |
| 462 | `"AUDIT_WP-*.md"` | Error message |
| 463 | `"AUDIT_WP-*.md"` | Suggestion message |
| 481 | `"AUDIT_WP-*.md"` | Existence check message |
| 511 | `"AUDIT_WP-*.md"` glob | Audit file detection |

### scripts/session_closeout.py (3 locations)
| Line | Pattern | Type |
|------|---------|------|
| 63 | `r"WP-\d{4}-\d{3}"` | TICKET_RE constant |
| 275 | `r"-?\s*\*\*ID:\*\*\s*(WP-\d{4}-\d{3})"` | _resolve_active_ticket |
| 1072, 1078 | help text examples | CLI help strings |

### scripts/ticket_activity_monitor.py (1 location)
| Line | Pattern | Type |
|------|---------|------|
| 60 | `r"Plan\s+activo.*?:\s*(WP-\d{4}-[A-Za-z0-9]+)"` | Plan ID extraction |

### runtime/ui_state_projector.py (1 regex location)
| Line | Pattern | Type |
|------|---------|------|
| 59 | `r"\|\s*\*\*Plan ID\*\*\s*\|\s*(WP-\d{4}-...)"` | TURN.md Plan ID extraction |

### scripts/graph_context.py (2 regex locations)
| Line | Pattern | Type |
|------|---------|------|
| 162 | `r"\*\*ID:\*\*\s*(WP-\d{4}-\d{3})"` | Ticket ID extraction |
| 166 | `r"#\s*Work Plan\s*-\s*(WP-\d{4}-\d{3})"` | Title-based extraction |

### scripts/validate_authority.py (2 locations)
| Line | Pattern | Type |
|------|---------|------|
| 55 | `"WP-" in line` | Simple string check |
| 56 | `r"(WP-\d{4}-[A-Za-z0-9]+)"` | Regex extraction |

### scripts/archive_execution_log.py (1 location)
| Line | Pattern | Type |
|------|---------|------|
| 9 | `r"(?m)^###\s+WP-\d{4}-\d{3}\b.*$"` | Section header extraction |

### scripts/archive_collaboration_artifacts.py (4 locations)
| Line | Pattern | Type |
|------|---------|------|
| 24 | `r"^PLAN_WP-(\d{4})-(\d{3})\.md$"` | PLAN file glob |
| 25 | `r"^AUDIT_WP-(\d{4})-(\d{3})\.md$"` | AUDIT file glob |
| 43 | `f"WP-{year}-{num}"` | Generator in parse_wp_number |
| 55 | `r"(?m)-?\s*\*\*ID:\*\*\s*(WP-\d{4}-\d{3})"` | get_active_wp ID extraction |

### .agent/agent_controller.py (5 locations)
| Line | Pattern | Type |
|------|---------|------|
| 2332-2333 | `"PLAN_WP-"` / `"AUDIT_WP-"` | Workspace exclusion path prefixes |
| 3040,3297,3364,3485 | `"Use --ticket WP-XXXX"` | Error messages |
| 3004-3010 | `"WP-2026-069"` in template strings | Notification templates |

## Category B: Generators → must emit `WT-` for new tickets

### bus/supervisor.py
| Line | Code | Type |
|------|------|------|
| 455 | `f"WP-{prefix}-{last_num + offset:03d}"` | Ticket queue candidate generator |
| 607 | `f"WP-{prefix}-{int(number) + 1:03d}"` | _next_ticket_id generator |

### scripts/archive_collaboration_artifacts.py
| Line | Code | Type |
|------|------|------|
| 43 | `f"WP-{year}-{num}"` | parse_wp_number return (preserve original prefix) |

## Category C: Tests/Fixtures → NOT changed (historical data)

- `tests/test_manager_review_bridge.py`: ~120 WP- occurrences (test data with WP-2026-XXX and WP-TEST-XXX)
- `tests/test_supervisor.py`: ~260 WP- occurrences (test data with WP-2026-XXX and WP-TEST-XXX)
- `tests/test_agent_controller.py`: 4 WP- occurrences (PLAN_WP-, AUDIT_WP- path prefixes in test data)

Note: Test data fixtures remain as WP- for backward compatibility verification. New tests will be added to verify WT- works identically.

## Category D: Docs/Comments → NOT changed (historical references)

- All `# WP-2026-NNN:` comment annotations in code (hundreds of occurrences)
- CHANGELOG.md
- memory files (observations.jsonl, MEMORY.md, memory_rules.md, memory_profile.md)
- PROJECT.md historical references
- AGENTS.md, README.md, etc.

## Summary
- **Category A (Parsers):** ~45 regex/string occurrences across 11 files
- **Category B (Generators):** 2 primary generators in bus/supervisor.py + 1 in archive_collaboration_artifacts.py
- **Category C (Tests):** 2 test files to add verification tests; existing data unchanged
- **Category D (Docs/Comments):** Not touched
