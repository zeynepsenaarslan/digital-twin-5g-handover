# Reproduction with an external ns-3 installation

## Tested environment and exact dependency identities

- WSL2 Ubuntu 24.04, Python 3.12, C++ compiler supported by ns-3.48, CMake/Ninja.
- ns-3 tag observed: `ns-3.48`; commit `d2add90b452d600cfb4859baed8e9ea633519447`.
- NR environment was called “v5.0.y” during the project; the observed Git tag is `v5.0`, commit `47a3adc263f773556eaadac5a5341458dbc61c47`.
- Matplotlib 3.11.2; exact Python dependency versions in `analysis/requirements-lock.txt`.

The exact observed NR source exposes `NrUePhy::ReportUeMeasurements`, `NrA3RsrpHandoverAlgorithm`, `NrPointToPointEpcHelper::SetupRemoteHost`, `NrHelper::AddX2Interface`, and real RRC. Do not assume every release with a similar name has identical signatures or RSRQ behavior. The checked source derives RSRQ from cell power estimates and noise. Its standards compliance has not been separately validated.

Upstream ns-3 and NR sources are intentionally not bundled. Prepare these dependencies separately using their own installation instructions. Additional Python packages required for plotting are installed only into a virtual environment.

## Safe integration

Work from the independent research repository root. Replace the external path below. These instructions must not be run against the original working research checkout unless you have separately decided to modify it.

```bash
export RESEARCH_ROOT="$(pwd -P)"
export NS3_ROOT="/absolute/path/to/a/separate-compatible-ns-3-checkout"

test -f "$NS3_ROOT/ns3"
test -d "$NS3_ROOT/contrib/nr"
python3 - <<'CHECK'
import os
from pathlib import Path
source = Path(os.environ['RESEARCH_ROOT'])/'simulation/dt-handover-simulation.cc'
target = Path(os.environ['NS3_ROOT'])/'scratch/dt-handover-simulation.cc'
# Exclusive creation refuses to overwrite any existing simulation.
with target.open('xb') as stream:
    stream.write(source.read_bytes())
CHECK
```

The scratch build auto-discovers the simulation. Its `.gitignore` may hide the copied C++ file in the external tree; the authoritative research copy is tracked here under `simulation/`.

## Build and run in the external checkout

For a fresh compatible checkout (skip configuration if already correctly configured):

```bash
cd "$NS3_ROOT"
./ns3 configure --enable-examples --enable-tests
./ns3 build dt-handover-simulation -j 1
```

Do not claim build success until the command completes. If cached build metadata and wrapper profile disagree, investigate them within that external checkout. The historical local experiment used an existing release build; its full dependency rebuild was not revalidated during repository preparation.

Create unique run paths before executing. Do not use a directory that already contains CSV outputs:

```bash
cd "$RESEARCH_ROOT"
tag=$(date +%Y%m%d-%H%M%S)
export BASELINE="$RESEARCH_ROOT/runs/${tag}-baseline30"
export B3="$RESEARCH_ROOT/runs/${tag}-b3-45s"

cd "$NS3_ROOT"
./ns3 run "dt-handover-simulation --enableHandover=0 --simTime=30 --outputDir=$BASELINE" --no-build
./ns3 run "dt-handover-simulation --enableHandover=1 --simTime=45 --outputDir=$B3" --no-build
```

`--no-build` is valid only after successful compilation. Paths containing spaces require additional quoting through the ns3 wrapper; prefer checkout and run paths without spaces. The program refuses to replace existing output CSVs.

## Python setup and C1 QoS analysis

```bash
cd "$RESEARCH_ROOT"
python3 -m venv .venv-analysis
.venv-analysis/bin/python -m pip install -r analysis/requirements-lock.txt

.venv-analysis/bin/python -B analysis/phase_c1_qos.py   --input-dir "$BASELINE" --output-dir "${BASELINE}-qos" --window-ms 100
.venv-analysis/bin/python -B analysis/phase_c1_qos.py   --input-dir "$B3" --output-dir "${B3}-qos" --window-ms 100
```

C1 uses standard-library Python and does not require Matplotlib. Output: packet delay CSV, window QoS CSV, summary JSON, and validation report. Its single-UdpClient contract assumes zero-based contiguous successful-send sequence numbers with no wrap. It counts duplicates separately and does not fabricate TX records for missing packets.

## C2.1 radio validation

For a self-contained structural smoke check, the reference can be the same run. **This does not prove regression equality to an independent reference.**

```bash
.venv-analysis/bin/python -B analysis/validate_phase_c21_radio.py   --run-dir "$B3" --reference-dir "$B3"
```

For a real passive-logging regression check, use a separately preserved validated same-scenario run as the reference:

```bash
# Replace with an actual independent reference directory; not bundled here.
export REFERENCE_B3="/absolute/path/to/validated-b3-run"
.venv-analysis/bin/python -B analysis/validate_phase_c21_radio.py   --run-dir "$B3" --reference-dir "$REFERENCE_B3"
```

Repeat with baseline/reference-baseline directories as needed. The validator checks schema, finite values, units, per-stream time order, serving attribution, RSRP/RSRQ pairs, and post-handover target measurements. It also requires all five legacy CSVs to match the reference byte-for-byte. It is deliberately specific to UE index 0, IMSI 2, BWP 0, and cells 1/2.

## C2.3 plotting and tests

```bash
.venv-analysis/bin/python -B analysis/phase_c23_plots.py   --radio-run "$B3" --qos-dir "${B3}-qos"   --output-dir "${B3}-plots" --zoom-seconds 1

.venv-analysis/bin/python -B -m unittest discover   -s analysis -p 'test_phase_*.py' -v
```

Plot outputs are PNG at 300 DPI and SVG. The script uses Agg, stores its Matplotlib cache in its new output directory, refuses overwrites, verifies that QoS packets match the radio run, and reads handover markers from actual events. It never fills measurement gaps. SINR is not implemented.

Repository preparation checks exercise copied Python code using existing external CSVs; they do not rebuild the external simulator or establish that an arbitrary fresh dependency installation is compatible.
