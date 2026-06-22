---
description: Mine recent Claude Code transcripts for recurring patterns and propose new skills/memories — incremental (watermark), Haiku-subagent fan-out, human-gated.
argument-hint: "[max_sessions] (default 15) — caps work per run so you can spread it over time"
---

Distill durable learnings from my recent Claude Code sessions into proposed skills and memories.
Be incremental and cheap, and DO NOT write anything until I approve.

## Procedure

1. **Watermark.** Read `~/.claude/.distill-watermark` (an ISO timestamp; if missing, treat as "process everything", but still cap by max_sessions). Let `MAX=${1:-15}`.

2. **Find new sessions.** List transcripts under `~/.claude/projects/*/*.jsonl` whose mtime is newer than the watermark. Sort oldest-first and take at most `MAX`. Report how many total are pending and how many you're processing this run (so I know how much backlog remains — this is meant to be run repeatedly).

3. **Fan out on Haiku (cost discipline).** For each selected transcript, spawn a subagent with **model haiku** to read it and return candidate learnings as structured items. Each candidate: `{type: skill|memory, title, evidence (session id + 1-line quote), one-line summary}`. Tell each subagent to look for:
   - Recurring *workflows* I repeat or correct (→ skill candidates).
   - Preferences / conventions / "don't do X, do Y" guidance I gave (→ skill or memory).
   - Durable project facts, decisions, or setup details not in the repo (→ memory).
   - Gotchas / failure modes worth not rediscovering.
   Skip ephemeral chatter. Return nothing rather than padding.

4. **Cluster + dedupe.** Merge candidates that describe the same thing. Drop anything already covered by an existing skill in `~/.claude/skills/` or an existing memory in the memory dir (read their names/descriptions first).

5. **Apply a recurrence bar.** Propose a **skill** only if the pattern recurs across **≥2 sessions** (one-offs are too thin — every skill costs always-on description tokens in every session). Propose a **memory** for durable single facts. When unsure, prefer a memory (cheaper, no always-on cost).

6. **Present, don't write.** Show a numbered table of proposals: `# | type | name | scope (global/project) | why | draft body`. For skills, recommend global vs project scope per the chezmoi/skills hygiene (domain-specific → project). Then stop and ask which to accept.

7. **On approval only:**
   - Skills → write `~/.claude/skills/<name>/SKILL.md`, then `chezmoi add` it into the dotfiles repo (see the `chezmoi` skill) on a branch; don't commit without asking.
   - Memories → write to the memory dir following the memory format; add the one-line pointer to MEMORY.md.
   - Update `~/.claude/.distill-watermark` to the newest processed session's mtime.

## Notes
- This is per-machine (transcripts differ by machine); run it on each box and consolidate proposals.
- First run on a fresh machine clears the backlog in `MAX`-sized batches; once caught up, a light `/schedule` cadence keeps it current.
- Never auto-write skills — skill proliferation is a real cost. Human gate is mandatory.
