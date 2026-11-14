# Memory Curator — Harness Adapters

`curator install` ships the same core into every supported harness.
The core (CLI + skills) is harness-agnostic; an adapter is **delivery
only** — no logic lives in a harness-specific piece.

## What every adapter delivers

| Piece | What | Source |
|-------|------|--------|
| Skills | `curator-save`, `mapping-documentation`, `curator-update-docs` | `.agents/skills/` (copied; dev symlinks preserved) |
| Commands | `/curator-save`, `/curator-create-map`, `/curator-status`, `/curator-query`, `/curator-report`, `/curator-full` | `integrations/commands.json` |
| Rules section | One `Memory Curator` section (memory rules + routes-catalog pointer + regen hint) | `integrations/curator-rules.md`, path substituted at install |
| State config | Knowledge base path → `~/.curator/config.json` | `curator.state` |

No MCP servers, no daemons, no plugins, no background processes
(decision 2026-10-03). Everything the agent does, it does by running
the `curator` CLI.

## Adapter map

| Harness | Skills dir | Rules file | Commands mechanism |
|---------|-----------|------------|--------------------|
| OpenCode | `~/.config/opencode/skills/` | `~/.config/opencode/AGENTS.md` | `command` section of `opencode.json` (retired entries cleaned on reinstall) |
| Claude Code | `~/.claude/skills/` | `~/.claude/CLAUDE.md` | `~/.claude/commands/<name>.md` files (retired files unlinked) |

Retired commands/skills (`curator-project-save`, `curator-setup`,
`curator-start`, `curator-stop`, `curator-worker`) are removed by
reinstall — upgrading never leaves dead entries behind.

## Adding a new harness

One function in `core/curator/installer.py`:

1. call `_install_skills(<harness skills dir>, skills_mode)` — shared;
2. ship commands from `_commands_source()` in the harness's own format
   (json section, md files, whatever the harness reads);
3. call `_install_global_rules(<rules file>, _rules_section(base))` and
   `_remove_stale_routes_pointer(<rules file>)` — shared, idempotent;
4. base persists via `write_configured_base(base)` — shared, do not
   invent a per-harness base config.

Detection: extend `detect_harnesses()`; expose a `--<harness>` flag in
`cmd_install()`. That's it — the adapter must not import any
harness-specific runtime; the agent only ever calls the CLI.

## Routes catalog pointer (placement M2)

The routes catalog `<base>/knowledge-routes.md` lives in the knowledge
base and is read by the agent on demand. `curator install` (and
`curator knowledge-routes --write`) publish one rules section pointing
at it: read the catalog's "When to use" sections when a task touches a
known topic, then open the source file. Catalog content never goes into
the rules file. `curator save` regenerates the catalog in the same
commit as the facts, so it never goes stale.

Placement decision (pointer instead of preloading) — experiment 05,
see [ADR 003](../design/decisions/003-delivery-decision.md).
