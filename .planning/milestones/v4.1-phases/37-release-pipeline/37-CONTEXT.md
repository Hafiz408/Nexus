# Phase 37: release-pipeline - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

Modify `.github/workflows/build.yml` and `extension/.vscodeignore` so that:
1. Platform binaries (`nexus-backend-mac.tar.gz`, `nexus-backend-win.tar.gz`) and `checksums.sha256` are uploaded as permanent GitHub Release assets on tagged pushes
2. The `bin/` directory is excluded from the packaged `.vsix`, reducing size from ~62 MB → ~1.5 MB
3. The published VSIX contains only compiled extension code — no native binaries

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pure infrastructure phase.

Key context for planning:
- Existing workflow: `build-mac` and `build-win` jobs already produce the `.tar.gz` archives and upload them as expiring workflow artifacts; `package` job currently downloads those artifacts and bundles them in the VSIX
- The `.vscodeignore` file currently does NOT include `bin/**` — this needs to be added
- `gh` CLI is available by default in GitHub Actions runners; `GITHUB_TOKEN` has `contents: write` permission when declared
- Phase 36 already hardcoded the download URL template: `https://github.com/Hafiz408/Nexus/releases/download/v{version}/{archive}` — archive names must match exactly: `nexus-backend-mac.tar.gz`, `nexus-backend-win.tar.gz`, `checksums.sha256`
- Checksum format from Phase 36 CONTEXT.md: standard `sha256sum` line format `<hash>  <filename>` (two spaces, POSIX `sha256sum` output)
- Only triggered on `push: tags: v*` — no release upload on `workflow_dispatch`

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `.github/workflows/build.yml` — full pipeline exists; only needs targeted modifications
- `extension/.vscodeignore` — exists; needs `bin/**` entry added
- `build-mac` job: produces `extension/bin/nexus-backend-mac.tar.gz`
- `build-win` job: produces `extension/bin/nexus-backend-win.tar.gz`
- `package` job: currently downloads both binaries from artifacts before running `vsce package`

### Established Patterns
- `actions/upload-artifact@v4` / `actions/download-artifact@v4` already used for inter-job artifact passing
- `needs:` dependency chains already established
- Tag-gated behavior already present: `on: push: tags: v*`
- `gh release create` / `gh release upload` (GitHub CLI) is the modern standard for release asset uploads

### Integration Points
- Phase 36's `SidecarManager` fetches from: `https://github.com/Hafiz408/Nexus/releases/download/v{version}/{archiveName}`
- `_fetchChecksum` fetches: `https://github.com/Hafiz408/Nexus/releases/download/v{version}/checksums.sha256`
- These URLs must be satisfied by this pipeline

</code_context>

<specifics>
## Specific Ideas

- Add a dedicated `github-release` job that runs after both builds, downloads both artifacts, computes SHA256 checksums, creates the GitHub Release, and uploads all three assets atomically
- The `package` job should then depend on `github-release` (ensuring builds are done) and NOT download binaries for VSIX bundling
- Add `bin/**` to `.vscodeignore`
- The workflow needs `permissions: contents: write` at the job or workflow level for `gh release` commands

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>
