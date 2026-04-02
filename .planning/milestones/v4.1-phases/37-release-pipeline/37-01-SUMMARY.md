---
phase: 37-release-pipeline
plan: 01
subsystem: infra
tags: [github-actions, github-releases, vsix, pyinstaller, sha256, ci-cd]

# Dependency graph
requires:
  - phase: 36-sidecar-download
    provides: SidecarManager with hardcoded GitHub Releases download URLs (nexus-backend-mac.tar.gz, nexus-backend-win.tar.gz, checksums.sha256)
  - phase: 35-build-pipeline
    provides: build-mac and build-win CI jobs producing .tar.gz artifacts

provides:
  - github-release CI job that uploads platform binaries + checksums.sha256 as permanent GitHub Release assets on tagged pushes
  - bin/** exclusion in extension/.vscodeignore eliminating ~62 MB of native binaries from VSIX
  - Updated package job that depends on github-release and no longer bundles binaries

affects: [future-releases, vsix-distribution, sidecar-download]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "gh release create for atomic multi-asset release upload"
    - "workflow-level permissions: contents: write for gh CLI release commands"
    - "always() && !failure() && !cancelled() for jobs with skippable dependencies"
    - "Separate assets/ staging directory (not extension/bin/) for release artifact assembly"

key-files:
  created: []
  modified:
    - .github/workflows/build.yml
    - extension/.vscodeignore

key-decisions:
  - "Separate assets/ staging directory instead of extension/bin/ for release artifact assembly — avoids confusion with VSIX bin path"
  - "if: always() && !failure() && !cancelled() on package job — allows package to run when github-release is skipped (workflow_dispatch) while still blocking on actual failures"
  - "Workflow-level permissions: contents: write (not job-level) — applies uniformly across all jobs"

patterns-established:
  - "Pattern: gh release create with --generate-notes for automatic release note generation"
  - "Pattern: sha256sum <file1> <file2> > checksums.sha256 for multi-file checksum manifest"

requirements-completed: [DIST-06, DIST-07, DIST-08]

# Metrics
duration: 8min
completed: 2026-04-02
---

# Phase 37 Plan 01: GitHub Release assets and binary-free VSIX Summary

**CI now uploads nexus-backend-mac.tar.gz, nexus-backend-win.tar.gz, and checksums.sha256 as permanent GitHub Release assets on tag push; VSIX shrinks from ~62 MB to ~1.5 MB with bin/** excluded**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-01T19:59:01Z
- **Completed:** 2026-04-01T20:07:00Z
- **Tasks:** 2 of 2
- **Files modified:** 2

## Accomplishments

- Added `github-release` CI job that downloads both platform artifacts, generates SHA256 checksum manifest, and uploads all three files atomically via `gh release create` — satisfying Phase 36's hardcoded download URL pattern
- Stripped `bin/` from VSIX by adding `bin/**` to `extension/.vscodeignore` — eliminates the ~62 MB AV false-positive payload
- Updated `package` job with correct dependency chain (`needs: [build-mac, build-win, github-release]`) and `always() && !failure() && !cancelled()` gate so VSIX still builds on `workflow_dispatch` where `github-release` is skipped

## Task Commits

Each task was committed atomically:

1. **Task 1: Add github-release job to build.yml** - `bf4a5e8` (feat)
2. **Task 2: Strip binaries from VSIX and update package job** - `37bb24f` (feat)

## Files Created/Modified

- `.github/workflows/build.yml` - Added `permissions: contents: write`, new `github-release` job, updated `package` job (dependency chain + removed binary download steps)
- `extension/.vscodeignore` - Added `bin/**` to exclude native binaries from VSIX

## Decisions Made

- Used separate `assets/` staging directory (not `extension/bin/`) for release artifact assembly — avoids confusion between build artifact staging and extension binary path
- Used `if: always() && !failure() && !cancelled()` on `package` job so it runs on `workflow_dispatch` (where `github-release` is skipped) but still blocks on real upstream failures
- Placed `permissions: contents: write` at workflow level (not job level) for cleaner, unified permission declaration

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. `gh` CLI uses the built-in `GITHUB_TOKEN` with the declared `contents: write` permission — no additional secrets needed.

## Next Phase Readiness

- Phase 37 (release-pipeline) is complete — v4.1 milestone is now fully implemented
- The full v4.1 AV-safe distribution chain is in place:
  - Phase 36: SidecarManager downloads from GitHub Releases, verifies SHA256, shows progress
  - Phase 37: CI uploads the Release assets that Phase 36 downloads
- Next: v4.1 milestone completion and archive

## Self-Check: PASSED

- FOUND: .github/workflows/build.yml
- FOUND: extension/.vscodeignore
- FOUND: .planning/phases/37-release-pipeline/37-01-SUMMARY.md
- FOUND: bf4a5e8 (Task 1 commit)
- FOUND: 37bb24f (Task 2 commit)

---
*Phase: 37-release-pipeline*
*Completed: 2026-04-02*
