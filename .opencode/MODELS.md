# OpenCode Models Catalog

**Captured:** 2026-05-15
**Source:** `opencode models` (CLI v1.4.11)
**Authenticated provider:** OpenCode Go api (only credential present in `~\.local\share\opencode\auth.json`)

## Current Selection

`opencode-go/qwen3.5-plus` is the model wired into `.opencode/opencode.json` for the Builder.

The display name "Qwen3.5 Plus" is not a valid model ID. Always use the namespaced ID `opencode-go/qwen3.5-plus`.

## Launcher Integration (WP-2026-067)

The repo-local launcher `scripts/launch_agent_terminals.ps1` now invokes OpenCode with a composed prompt and canonical files attached:

```powershell
opencode run "<msg>" --agent builder --model <model> --dir <root> -f <canonicals>
```

**Prompt composition:**
- Ticket ID extracted from `.agent/collaboration/work_plan.md`
- Includes reminder to follow `Files Likely Touched` whitelist
- Mandatory closure instruction: emit `BUILDER_EXIT` and run `--mark-ready --json --force`

**Canonical files attached via `-f`:**
- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/execution_log.md`
- `.agent/collaboration/STATE.md`
- `.agent/collaboration/PLAN_<ticket>.md` (if exists)
- `.agent/collaboration/AUDIT_<ticket>.md` (if exists)

**Model selection:**
- Read from `.opencode/opencode.json` (`model` field)
- Never hardcoded in the launcher
- Current default: `opencode-go/qwen3.5-plus`

This eliminates the manual paste step that was required in WP-2026-066 and earlier.

## Paid Catalog (`opencode-go/*`)

- `opencode-go/deepseek-v4-flash`
- `opencode-go/deepseek-v4-pro`
- `opencode-go/glm-5`
- `opencode-go/glm-5.1`
- `opencode-go/kimi-k2.5`
- `opencode-go/kimi-k2.6`
- `opencode-go/mimo-v2.5`
- `opencode-go/mimo-v2.5-pro`
- `opencode-go/minimax-m2.5`
- `opencode-go/minimax-m2.7`
- `opencode-go/qwen3.5-plus`
- `opencode-go/qwen3.6-plus`

## Free Catalog (`opencode/*`)

Useful as zero-cost fallback for Builder smoke tests or rate-limited situations.

- `opencode/big-pickle`
- `opencode/deepseek-v4-flash-free`
- `opencode/minimax-m2.5-free`
- `opencode/nemotron-3-super-free`
- `opencode/qwen3.6-plus-free`

## How to Refresh

```powershell
Set-Location <repo_root>
opencode models 2>&1 | Tee-Object -FilePath .\opencode\opencode_models_latest.log
```

If `opencode models` fails, run `opencode auth list` first; the catalog depends on the authenticated provider.

## Rate Limits (OpenCode Go paid tier)

Server-side limits per credential, captured 2026-05-15. The Builder hits 429 / hard refusal if these are exceeded — there is no local counter today.

| Model | per 5h | per week | per month |
|-------|-------:|---------:|----------:|
| GLM-5.1 | 880 | 2,150 | 4,300 |
| GLM-5 | 1,150 | 2,880 | 5,750 |
| Kimi K2.5 | 1,850 | 4,630 | 9,250 |
| Kimi K2.6 | 1,150 | 2,880 | 5,750 |
| MiMo-V2.5 (≤256K) | 2,150 | 5,450 | 10,900 |
| MiMo-V2.5-Pro | 1,290 | 3,225 | 6,450 |
| MiniMax M2.7 | 3,400 | 8,500 | 17,000 |
| MiniMax M2.5 | 6,300 | 15,900 | 31,800 |
| Qwen3.6 Plus | 3,300 | 8,200 | 16,300 |
| **Qwen3.5 Plus** (current Builder) | **10,200** | **25,200** | **50,500** |
| DeepSeek V4 Pro | 3,450 | 8,550 | 17,150 |
| DeepSeek V4 Flash | 31,650 | 79,050 | 158,150 |

Free tier (`opencode/*`) limits not documented here.

## Notes

- The two namespaces are separate: `opencode/*` is the free tier, `opencode-go/*` is the paid tier. They are not interchangeable.
- "Qwen3.5 Plus" (paid) lives only under `opencode-go/`. The closest free alternative is `opencode/qwen3.6-plus-free` (note: different version).
- This catalog can change between CLI versions. Re-run `opencode models` after upgrading OpenCode.
- Qwen3.5 Plus has the most generous quota of the high-tier models — chosen as Builder default partly for that reason.
