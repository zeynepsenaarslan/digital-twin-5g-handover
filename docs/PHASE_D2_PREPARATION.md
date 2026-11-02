# D2 preparation and verification

This preparation preserves the two original Git indexes, the 16 staged D1 files,
49 baseline-protected files, and all 32 D1 release files (12 raw release CSVs in
the multi-UE reference). Work occurs on `review/d2-handover-studio-prep` in a
separate worktree using an independent `GIT_INDEX_FILE`. Original standalone
untracked D2 files are left intact; synchronized versions live on the preparation
branch. Source origins, old/new hashes and missing-file status are recorded in
[PHASE_D2_SYNC_PROVENANCE.json](PHASE_D2_SYNC_PROVENANCE.json).

No C or D0 history was recreated. Main/origin-main initially pointed to d41e126;
C2.2 is 6805334. The first commit preserves all 16 staged D1 files byte-for-byte,
including the five small static documentation figures. The second preserves the
D2 foundation. The third synchronizes the current D2 sources/tests and explicit
UE power profile. The fourth records evidence, current documentation and the
Studio V1 plan. Commit timestamps are real preparation times; no historical
author/committer dates are supplied. No push is authorized by this preparation.

## Why the wrapper reported an unknown test suite

The failure is reproducible without changing sources or libraries:

- `.lock-ns3_linux_build` selects `BUILD_PROFILE='debug'`,
  `ENABLE_TESTS=False`, `ENABLE_EXAMPLES=False`.
- `cmake-cache/CMakeCache.txt` selects release, `NS3_TESTS=ON`,
  `NS3_EXAMPLES=ON`.
- `test.py:1249` chooses the runner suffix from the lock profile;
  `test.py:1525` asks that runner for its suite list.
- The verbose wrapper command tried `build/utils/ns3.48-test-runner-debug`,
  which does not exist, and received shell return code 127. Its empty suite list
  then became the misleading `unknown test suite` message, wrapper exit code 2.
- The release `build/utils/ns3.48-test-runner` exists, lists
  `nr-handover-target`, and links the expected `libns3.48-nr-test.so` via its
  build/lib RUNPATH. `nm -C` confirms `NrHandoverTargetTestSuite` in that library.
  The source suite name is `nr-handover-target` in
  `contrib/nr/test/nr-test-handover-target.cc:430`, included in NR CMake test sources.

The earlier suspicion that the test library was too old was not supported.
No rebuild or model patch was needed to execute the actual release suite:

```bash
build/utils/ns3.48-test-runner --suite=nr-handover-target --fullness=QUICK --verbose
```

It ran and returned 0, with PASS for the suite and both registered QUICK cases:
`4 cells and A2-A4-RSRP algorithm` and `4 cells and strongest cell algorithm`.
This is a bounded native regression, not a policy comparison experiment.
The broken wrapper invocation is not reported as PASS. The lock was not edited;
future wrapper builds/runs must first reconcile configuration metadata in a
separate compatible build. Direct release invocation is the verified path here.

## Verification scope

[PHASE_D2_PREPARATION_VALIDATION.json](PHASE_D2_PREPARATION_VALIDATION.json)
records current results and evidence hashes. Python tests run from the prepared
standalone analysis sources with `D2_RUN_DIR` set to the corrected full-a native
dataset, so integration checks are enabled. Strict offline analysis rechecks the
recorded seed-1 A/B pair and seeds 2/3. These are reanalyses, not newly executed
D2 simulations. The native suite and a fresh 45 s D1 simulation are actual new
executions. Fresh D1 results are compared against the preserved release data.

The recorded D2 binary/library manifest matches current artifacts. One diagnostic
header differs from the run-time source snapshot only by a Doxygen `@param`
comment; the archived tested source and unchanged binary hash preserve that
provenance. No native source was modified and no dependency rebuild is claimed.
The 23 dBm scenario cannot be used as evidence of improvement under unchanged
radio conditions. D2 remains incomplete.

## Artifact selection

Only allowlisted sources, tests and required documentation are included. Five D1
PNG figures are the already-staged documentation assets, not raw experiment
exports. Raw/derived experiment CSVs, logs, binaries, build/cache directories,
local configuration, `references/paper.pdf`, and `*:Zone.Identifier` are excluded.
The existing ignore rules cover output/cache/environment directories but not all
CSV/log/PDF paths, so explicit file selection is essential. Root ignore and D1
documents remain untouched. Local logs containing environment paths are retained
outside Git; published provenance uses relative source labels.

[The Studio V1 plan](STUDIO_V1_PLAN.md) is the next implementation scope on a
separate branch. No UI code, engine change, D3 expansion or D2 release declaration
is included in these four commits.
