# Phase C2.2: passive native downlink SINR

Implemented and validated on 19 October 2026 against the installed ns-3.48 / NR v5.0 source. No PHY, scheduler, propagation, mobility, traffic, RNG or A3 parameters were changed. A3 remains RSRP-triggered.

## Native API and semantics

- `contrib/nr/model/nr-ue-phy.cc:158,162`: TypeId sources `DlDataSinr` and `DlCtrlSinr`.
- `contrib/nr/model/nr-ue-phy.h:324,334`: both callbacks are `void(uint16_t cellId, uint16_t rnti, double sinr, uint16_t bwpId)`.
- `nr-ue-phy.cc:1435`: `GenerateDlCqiReport` emits DATA when UL is configured, RNTI is nonzero and reception is enabled. `ComputeAvgSinr` (line 556) averages linear ratios across all spectrum bands, including zeros. An empty spectrum returns DBL_MAX.
- `nr-ue-phy.cc:1788`: CONTROL averages nonzero spectrum entries. It can report before RRC attachment. DATA and CONTROL do not have identical averaging support or sampling times.
- `contrib/nr/helper/nr-helper.cc:462` wires the SISO data callback. The installed default is `CQI_PDSCH_SISO`; this implementation does not change CSI configuration merely to emit traces.

The native values are linear power ratios. Only finite, positive, non-sentinel values are converted using `10 * log10(linear)`. dB conversion follows averaging; it is not an average of per-band dB values. These are simulation model measurements, not independently calibrated hardware measurements or a per-resource-element standards validation. High modeled dB values are retained without clipping.

## Implementation and CSV

`scratch/dt-handover-simulation.cc:36` adds `SinrMeasurementLogger`. `Record` only reads identifiers, simulation time and the native ratio, then writes a separate file. `Close` checks writing. At line 689, `TraceConnectWithoutContext` connects exactly once per UE/BWP to each source. `MakeCallback(...).Bind(...)` supplies the UE device, its index and channel label; the trace supplies cell/RNTI/ratio/BWP. No simulator event, random number or configuration is changed.

`sinr_measurements.csv` columns:

| Column | Meaning |
|---|---|
| time_ns, time_s | Same ns-3 time, integer ns and decimal seconds |
| ue_id | Existing mobility-log UE index |
| imsi | Full-width UE device IMSI |
| rnti | Native trace RNTI; zero before connection is preserved |
| cell_id | Current cell from the trace, including after handover |
| bwp_id | Native trace BWP identity |
| channel_type | DL_DATA or DL_CONTROL |
| sinr_linear | Original dimensionless power ratio |
| sinr_db | Derived dB; blank for invalid values |
| valid, status | Conversion eligibility and reason |
| source | Exact NrUePhy trace name |

Zero, negative, NaN, infinity and DBL_MAX sentinel observations are retained with blank dB and an explicit reason. Zero linear power is not replaced by zero dB. Five actual CONTROL samples have RNTI zero before attachment; IMSI remains available from the bound device. PHY events do not correspond one-to-one to UDP payload packets. No neighbour-cell SINR is inferred.

## Actual validation

Run: `dt-output/phase-c22-20261019-140952-b3-45s`.
Backup: `research-backups/dt-handover-simulation-before-c22-20261019-140952-420046.cc`.
Independent reference: `dt-output/phase-c21-20261017-170148-b3-45s`.

| Result | Value |
|---|---|
| DATA samples, invalid | 4419, 0 |
| CONTROL samples, invalid | 14445, 0 |
| DATA time range | 0.021107141 to 43.992607141 s |
| CONTROL time range | 0.000035713 to 44.995035713 s |
| DATA range | 19.776730 to 77.023898 dB |
| CONTROL range | -5.130201 to 68.652860 dB |
| Samples after UE completion | DATA 329; CONTROL 1288 |
| DATA cells 1 / 2 | 4090 / 329 |
| CONTROL cells 1 / 2 | 13156 / 1289 |
| UE HO start / completion | 40.742171427 / 40.744035713 s |
| Target gNB completion | 40.748564480 s |
| Mobility / UDP TX / RX | 1501 / 4300 / 4299 |
| Received bytes / lost sequence | 2201088 / 3974 |
| Delivery ratio | 99.976744% |
| Active-window goodput | 0.409504744 Mbit/s |
| Mean received UDP delay | 2.771225671 ms |

PASS: six legacy CSVs byte-identical to independent reference (mobility, UDP packets, UDP traffic, handover events, RRC measurements, PHY RSRP/RSRQ). No run-to-run differences were observed. The existing one-packet loss remains; its responsible protocol layer is not established. PASS: per-stream timestamps, both sources, no exact duplicate records, source cell before handover and target cell afterwards. PASS: existing C2.1 validator and 19 Python tests. PASS: all 102 protected historical output files unchanged.

Build: one-job Ninja compilation of the simulation object and required prerequisites, followed by the CMake-generated linker command, succeeded. The wrapper metadata had a debug/release mismatch; `cmake -S . -B cmake-cache` regenerated it while retaining the cached release configuration. No installed library source was edited. A full all-target rebuild is not claimed.

## Reproduce in the original VS Code WSL terminal

Use new output paths each time. The recorded execution used:

```bash
./ns3 run 'dt-handover-simulation --enableHandover=1 --simTime=45 --outputDir=dt-output/phase-c22-20261019-140952-b3-45s' --no-build
.venv-analysis/bin/python -B analysis/phase_c22_sinr.py --run-dir dt-output/phase-c22-20261019-140952-b3-45s --reference-dir dt-output/phase-c21-20261017-170148-b3-45s
.venv-analysis/bin/python -B analysis/phase_c1_qos.py --input-dir dt-output/phase-c22-20261019-140952-b3-45s --output-dir dt-output/phase-c22-20261019-140952-qos --window-ms 100
.venv-analysis/bin/python -B analysis/phase_c23_plots.py --radio-run dt-output/phase-c22-20261019-140952-b3-45s --qos-dir dt-output/phase-c22-20261019-140952-qos --sinr-csv dt-output/phase-c22-20261019-140952-b3-45s/sinr_measurements.csv --output-dir dt-output/phase-c22-20261019-140952-plots
.venv-analysis/bin/python -B -m unittest discover -s analysis -p 'test_phase_*.py' -v
head -n 6 dt-output/phase-c22-20261019-140952-b3-45s/sinr_measurements.csv
```

For subsequent source changes, compile first with `./ns3 build dt-handover-simulation -j 1`; use `--no-build` only after successful compilation. The recorded target object command was `ninja -C cmake-cache -j 1 scratch/CMakeFiles/scratch_dt-handover-simulation.dir/dt-handover-simulation.cc.o`; the complete generated link command is preserved with the local run evidence.

## Python and figures

`phase_c22_sinr.py` validates schema, identity, times, channel/source agreement, invalid-value policy and conversion. Its regression CLI requires a real independent same-scenario reference for meaningful regression evidence; using the same run as reference proves only structural consistency.

`phase_c23_plots.py --sinr-csv ...` optionally adds two figures to the existing five. Without the option, the historical five-figure workflow remains available. SINR input must belong to the selected radio-run directory. `sinr_full` and `sinr_handover` each have PNG (300 DPI) and SVG output. DATA uses blue circles; CONTROL uses orange crosses. All valid actual points are used; invalid values remain missing. Dense SVG point layers are rasterized to limit size, with vector labels/axes; no sample reduction or interpolation occurs. Event markers are read from handover_events.csv.

Matplotlib 3.11.2 / Agg, existing virtual environment, no new dependency installation. Plot manifest verifies input SHA-256 preservation and counts (900 radio rows, 4299 packet rows, 450 windows, three events). All seven figures/fourteen image files were generated. The handover view shows changes in observed SINR around the cell transition; it does not establish that SINR caused the handover or quantify a general handover benefit. One UE and seed/run 1/1 provide no statistical confidence intervals.

No Digital Twin, AI policy, SINR-based handover, new radio trace configuration or publication is performed in this phase.
