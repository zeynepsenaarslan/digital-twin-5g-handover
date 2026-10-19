# Portability and provenance notes

The simulation and Python source/test files are byte-identical copies of the working research versions. See `source-manifest.json` for source-relative locations, byte sizes, and SHA-256 values. No original implementation logic was refactored during repository extraction.

- CLI paths are supplied by the caller; the Python code has no fixed `/home/...` input dependency.
- The main C++ program defaults to relative `dt-output`, refuses overwrites, and must be compiled in an external ns-3/NR checkout. It uses C++ filesystem support supplied by that environment.
- The current radio validator intentionally assumes one UE (index 0 / IMSI 2), BWP 0, and cell IDs 1/2. It is not a general multi-UE validator.
- C1 assumes the installed UdpClient's zero-based successful-send sequence contract and complete observation coverage from zero to the final traffic/mobility timestamp.
- The plotting module currently selects one UE/BWP, validates data correspondence, and only registers RSRP/model-derived RSRQ. Unknown radio metrics are rejected; C2.2 optionally reads separately validated native DATA/CONTROL SINR from sinr_measurements.csv. See PHASE_C22_README.md for source signatures, averaging and invalid-value semantics.
- Tests remain in `analysis/` to preserve their existing sibling imports. Use the documented discovery command or set the appropriate Python module search path.
- `docs/history/` contains exact educational notes from the original workspace. Their `scratch/`, `dt-output/`, dated filenames, and line numbers describe that historical workspace. Use the current reproduction guide for portable commands; historical absolute/local references are not required for execution.
- Selected SVGs are copied from actual C2.3 and C2.2 outputs, not re-rendered or fabricated. Full raw datasets and all environment/build caches are deliberately excluded. `examples/recorded-handover.csv` is an actual complete three-event example, not a full analyzer input dataset.
- Recorded results use seed 1/run 1. New toolchains, dependency versions, model changes, and different inputs may alter outputs. Byte-for-byte agreement must be checked rather than assumed.

Only research implementation files were extracted. No secrets, `.git` metadata, credentials, upstream code tree, dependency source, binaries, backup directory, or virtual environment was copied.
