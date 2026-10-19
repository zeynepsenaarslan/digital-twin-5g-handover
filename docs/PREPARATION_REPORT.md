# Local repository preparation review

No commit, remote, or publication has been performed. GitHub authentication is reviewed separately before publication.
The original simulator checkout was used read-only. Source/configuration,
results, backups, Git HEAD/remote/status, and detached state are preserved.

- 15 copied files verified against original bytes with SHA-256.
- 12 copied Python tests passed.
- Copied C1 analysis, C2.1 validator, and C2.3 rendering ran successfully using existing external data; smoke outputs stayed in a temporary directory.
- Reproduction commands are for a separate external simulator checkout. No new C++ integration/build or simulation run was performed during extraction.
- Relative Markdown links, intended file sizes, recognizable secret patterns, and exclusions were checked. Secret scans are heuristic, not a guarantee.
- No upstream simulator tree, virtual environment, builds, backups, or full datasets are included.
- The observed NR version is recorded by exact commit and tag; similarly named releases may differ in API behavior.
- Educational history files preserve old commands exactly; the current reproduction guide is authoritative for portable use.
- Updated 19 October 2026: the maintainer approved GPL-2.0-only for the research code; LICENSE and docs/LICENSING.md now record its scope. Existing third-party notices are preserved. No speculative copyright owner was declared.

## Before the first commit and eventual publication

Review the final staged content, licensing scope, author identity, and authentication. Do not commit, create the PUBLIC GitHub repository, add a remote, or push until the maintainer gives final publication confirmation. A successful single handover does not establish overall algorithm reliability.
