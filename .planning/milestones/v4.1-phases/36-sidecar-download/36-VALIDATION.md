---
phase: 36
slug: sidecar-download
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 36 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | TypeScript compiler (`tsc --noEmit`) — no runtime test framework for the extension |
| **Config file** | `extension/tsconfig.json` |
| **Quick run command** | `cd extension && npm run typecheck` |
| **Full suite command** | `cd extension && npm run typecheck` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd extension && npm run typecheck`
- **After every plan wave:** Run `cd extension && npm run typecheck`
- **Before `/gsd:verify-work`:** Typecheck green (0 errors) + manual VSIX smoke test

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 36-01-01 | 01 | 0 | DIST-01..05, PRES-01..03 | compile | `cd extension && npm install --save-dev @types/node@^20 && npm run typecheck` | ✅ | ⬜ pending |
| 36-02-01 | 02 | 1 | DIST-05 | compile | `cd extension && npm run typecheck` | ✅ | ⬜ pending |
| 36-02-02 | 02 | 1 | DIST-04 | compile | `cd extension && npm run typecheck` | ✅ | ⬜ pending |
| 36-03-01 | 03 | 2 | DIST-01, DIST-02, DIST-03 | compile | `cd extension && npm run typecheck` | ✅ | ⬜ pending |
| 36-03-02 | 03 | 2 | PRES-01, PRES-02, PRES-03 | compile | `cd extension && npm run typecheck` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `extension/package.json` — add `@types/node@^20` to `devDependencies`; run `npm install`
- [ ] Verify `cd extension && npm run typecheck` passes with 0 errors (currently 22 errors without `@types/node`)

*These must complete before any Wave 1 implementation tasks begin.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Progress notification "Downloading Nexus backend…" shown on first install | DIST-01, DIST-03 | Requires VS Code UI, not automatable via CLI | Install VSIX in fresh VS Code profile; observe download notification on first activate |
| No network call / no notification on warm path | DIST-02, PRES-02 | Requires observing absence of network activity | Activate again after first download; confirm no progress notification appears |
| Error notification + "Open GitHub Releases" button on download failure | DIST-04 | Requires triggering a real HTTP failure | Set download URL to invalid version tag; observe error message with action button |
| SHA256 mismatch aborts and corrupt archive deleted | DIST-05 (partial) | File deletion after mismatch is runtime behavior | Corrupt the downloaded file mid-test; confirm activation aborts and tmp file absent |
| All features (chat/index/explain/debug/review/test) work after cold-start | PRES-01 | End-to-end functional test requires VS Code + running backend | Download binary fresh, run each feature command, confirm normal operation |
| Dev mode (backend already running on port) → skip spawning | PRES-03 | Requires running a backend before activating extension | Start backend manually on port 8000; activate extension; confirm "skipping sidecar spawn" in output channel |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
