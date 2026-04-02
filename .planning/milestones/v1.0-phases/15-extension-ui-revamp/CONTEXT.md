# Phase 15: Extension UI Revamp — User Context

Captured via /gsd:discuss-phase, 2026-03-21.

## Core Problem

Polish & coherence. The code is functionally correct but the sidebar doesn't
feel like a real published extension yet — spacing, colors, and typography need
tightening across all sections.

## Focus Areas (all sections)

All four sections need attention:
- Index section (status dot, node count, re-index button layout)
- Chat + input area (message bubbles, textarea, send button, empty state)
- Citations (chip overflow, truncation, click targets)
- Activity log (log rows, progress row, badge counts)

## Specific Decisions

### Textarea
- **Auto-grow**: Textarea should expand from 1 row up to ~5 rows as the user
  types, then scroll. Feels natural for multi-line queries.

### Citation Overflow
- **Collapse**: Show the first 5 chips. If there are more, render a "+N more"
  chip that expands inline on click. Prevents citation floods on dense answers.

### Index Progress
- **Show progress bar**: During indexing, show `files_processed` count AND a
  thin progress bar if total is knowable. At minimum: "Indexing — 42 files…"
  with a thin animated/determinate bar.

### Theme Compatibility
- Target **both dark and light** VS Code themes.
- Must use VS Code CSS variables throughout — no hardcoded colors except where
  VS Code provides no variable (e.g. green status dot).
- Verify key variables work in both Light+ and Dark+.
