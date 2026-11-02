# D2: three-cell deterministic foundation

Status: **BLOCKED_NATIVE_HANDOVER; D2 is not complete or release-ready.**
The separate foundation producer/analyzer is implemented and tested. A reproducible
native gNB joining failure blocks the healthy-handover gate. GPL-2.0-only.

## Frozen design

D1 sources, analyzers, documentation and release outputs are protected by
`research-backups/d2-baseline-20261030/protected.json`. D2 is a separate
`scratch/dt-d2-simulation.cc` executable with independent helper/observers and
`analysis/phase_d2.py`. No upstream model changes and no D1 selector changes.

Sites are (0,0,25), (300,0,25), (150,259.807621135,25) m. One cell/site,
one shared 3.5 GHz/20 MHz BWP, numerology 1, 43 dBm, UMa, DirectPath ideal
beamforming. Preserve native antenna/channel/filter defaults and A3 1.5 dB,
128 ms, real RRC/EPC. Record effective settings separately from explicit ones.
All three X2 pairs are connected and logged using actual cell IDs.

| UE | Start (m) | Outbound velocity (m/s) | Initial gNB index |
|---|---|---|---|
|0|(20,20,1.5)|(5,0,0)|0|
|1|(280,20,1.5)|(-2.5,4.330127019,0)|1|
|2|(150,239.807621135,1.5)|(-2.5,-4.330127019,0)|2|
|3|(150,180,1.5)|(0,0,0)|2|
|4|(25,60,1.5)|(0,0,0)|0|

Default observation 90 s, reverse velocities at 40 s, stop at 80 s. The
turn time is configurable for short smoke runs; require 2*turn < duration-1.
Offline validation requires duration aligned to the 0.5 ms slot and sampling grids.
Motion is piecewise constant velocity, with exact scheduled changes before
same-time observations. Five independent 512-byte DL UDP flows, 10 ms,
from 1 s until duration-1, plus one-second drain. No forced HO, genie
measurements, radio tuning or expected HO count. Explicit initial attachment.

## Trace registry and semantics

All files are new D2 outputs. Simulation refuses an existing output directory.
UE index/IMSI/IPv4/flow/port and gNB/node/cell/BWP registries are authoritative;
RNTI is cell-local. One UE/BWP connection to each PHY trace; gNB events dispatch
by IMSI. Attempts are UE-local, including delayed gNB acknowledgements.

Native `NrGnbPhy::SlotDataStats` is emitted for processed slots by
`GenerateAllocationStatistics` (nr-gnb-phy.cc). Its misleading used-RE field
is actually count(RBG mask)*RB-per-RBG*num-symbols. Record it as
`allocated_prb_symbols`: DATA + MSG3, both UL and DL, allocation not successful
delivery or queue demand. Denominator is available PRBs * available data symbols
from the same callback; also retain full-slot symbols. Control symbols excluded
by native callback. Do not label this DL-only load, per-UE PRBs, or queue load.
Native raw rows include observed idle slots. The hook is inside DoStartSlot,
which is conditional on channel access/allocation (nr-gnb-phy.cc:832-872).
The initial 0.5 ms slot has no callback in smoke04; it is NOT zero-filled.
Validator explicitly permits only that bootstrap gap, records missing slot 1,
and masks the first 100 ms utilization window (valid=0, full-window fraction
missing). Observed-only allocation fraction and slot coverage remain available.
All other gaps, duplicates and overflow fail. Traffic begins at 1 s, after this gap.

`NrEpcGnbApplication::RxFromS1u` provides the inner IP packet after GTP removal
and successful tunnel lookup. Parse IPv4/UDP/SeqTsHeader on a COPY and log bound
ingress cell + UE/flow/sequence. Join actual application TX/RX to this ingress.
Cell QoS means **S1-U ingress-cell cohort end-to-end delivery**, not proof of
last radio transmission cell, including during X2 forwarding. Repeated ingress or an RX without ingress is rejected. Strict validation rejects
missing ingress; diagnostic mode can preserve unreceived TX without ingress in
`unattributed_packets_v3.csv` with no invented cell. No such missing ingress
occurred in the recorded 90 s runs.
Cell time series uses RX-time windows for goodput and received-only delay;
cohort delivery fraction uses ingress counts across the entire observation.
End-of-run missing packets remain undelivered, not proven permanent drops.

## Validation gates

1. Baseline: D1 validator and all 31 existing Python tests; protected hashes.
2. Build with existing examples/tests-enabled configuration; short five-UE smoke.
3. Exact CSV headers, no unknown/duplicate registries, all timestamps finite and
   nanosecond-exact; all five analytical outbound/return/stopped trajectories.
4. Initial attachment, all X2 pairs, source/target/IMSI/attempt lifecycle,
   native preceding RRC report and post-HO serving/SINR identities. Errors or
   incomplete attempts fail; zero HO for a particular UE is allowed.
5. Actual same-epoch RSRP for serving plus BOTH other cells, per-UE coverage;
   candidate ranks are PHY-observation ranks, not RRC policy candidates.
   Missing slots have measured=0 and missing value/rank; never fabricate power.
6. All slot counts/denominators and idle coverage (explicit bootstrap mask); per-cell PRB-symbol totals.
7. TX/RX/ingress joins, five-tuple FlowMonitor mapping, IP/application counts,
   per-cell QoS totals sum to per-UE/global totals; loss/unresolved separated.
8. Two identical configuration/seed runs: every raw CSV byte-identical.
   Corruption tests exercise schema, missing candidates, wrong cells/IMSI,
   overlapping/duplicate slots, motion boundaries, packet attribution and HO.
9. Recheck D1 protected hashes and validator after all work. Only then mark this
   D2 foundation complete; this is not D3 scaling or paper reproduction.

## Later controlled experiment

A3 vs A2/A4 is deferred. Freeze topology, trajectories, traffic, channel,
scheduler and explicit RNG streams; predeclare seed set, metrics, observation
windows and each algorithm's units. Change only policy configuration. Report
native candidate availability, failures/censoring and uncertainty. Do not tune
radio parameters to force handovers or compare unmatched D1/D2 populations.

## Design revision evidence

The initial centroid control at (150,86.602540378,1.5), explicitly attached to
cell 1, did not establish RRC by 1 s in smoke03 (UE3 IDLE_CELL_SEARCH,
attachments=0). Its actual 0.2 s PHY RSRPs were approximately -104.51/-92.75/
-93.26 dBm for cells 1/2/3. Exact failure mechanism is not established.
The foundation control is instead placed in the third site's interior at
(150,180,1.5), explicitly attached to gNB index 2. This is a documented topology
revision before baseline freeze; powers, channel, beams, A3 and seed are unchanged.
Multiple-neighbour visibility is still a hard measured-data gate for every UE.
Failed smoke outputs are retained and are not release evidence.

## Implemented diagnostics and gate behavior

`gnb_failures_v3.csv` passively connects all four native failure hooks:
HandoverFailureNoPreamble, HandoverFailureMaxRach, HandoverFailureLeaving and
HandoverFailureJoining. Joining/leaving events join only by native UE/IMSI,
cell and source/target RNTI to an actual recorded attempt. No completion is
synthesized. `gnb_context_v3.csv` reads the current UE cell/RNTI's actual gNB
`HasUeManager/GetUeManager` at simulation stop: presence, native IMSI/state and
pending gNB completion count. UE RRC state 9 means CONNECTED_NORMALLY;
gNB UeManager state 4 means CONNECTED_NORMALLY (different enum spaces).
An absent context has empty gNB IMSI/state, never a zero/default invented state.

Normal producer return code is 0 only when its accounting and complete UE/gNB
lifecycle checks pass. The recorded failed full runs return 1. Strict analyzer
rejects them and does not create a successful report. `--diagnostic` verifies
all raw CSVs and accounting while retaining the native failure, missing target
context and pending completion as **BLOCKED_NATIVE_HANDOVER**, returning 2.
`--compare-run` also validates both execution manifests and source/binary/library
hash equality. Identical failed runs never become PASS through repeatability.
Healthy single-run status is VALIDATED_SINGLE_RUN; healthy repeated full-gate
status would be PASS. That healthy full-gate result has NOT been obtained.

## Actual validation evidence (2026-10-30)

Build: existing ns-3 3.48 / NR v5.0 checkout, release configuration with examples
and tests ON; `./ns3 build dt-d2-simulation -j 1` succeeds. No all-target build
or full upstream test campaign is claimed. CMake regeneration rebuilt affected
dependencies; upstream model source files were not edited.

- Healthy smoke05: 6 s, turn 2 s, five attachments, 400 TX/RX per UE, no forced
  handovers, all 19 raw schemas and all-five-UE two-neighbour measurements valid.
- Full02/full03: 90 s, turn 40 s, stop motion 80 s, seed/run 1/1. All **19 raw
  CSV files byte-identical**, including native failure/context evidence.
- Adding the passive failure/context hooks preserved all 16 common observation
  CSVs from full01 byte-for-byte; only the trace registry gained hook rows.
- Five UE identities/flows, all X2 pairs and all outward/return/stopped mobility
  samples validated. Each UE has 450 epochs with serving + both neighbours.
- Radio rows 13,500; DATA/CONTROL SINR rows 240,237; native values/units/status,
  RRC preceding-target reports and source/target/RNTI/attempt ordering checked.
- 180,000 observed PRB slots per cell, exactly bootstrap slot 1 absent per cell.
  Allocated PRB-symbol totals: cell1 4,214,560; cell2 1,709,356; cell3 4,910,503.
  Observed native available PRBs are 53. These are actual allocation counters,
  not attached-UE-count estimates or DL-only utilization.
- Six derived CSV schemas are generated/read back and hashed. Cell-cohort
  received bytes sum to global UDP received bytes. All successful sends have
  one actual S1-U ingress in these runs. FlowMonitor/application counts match.
- 69 Python tests PASS: original 31, D2 contract/corruption tests and nine healthy
  native-dataset integration checks. `D2_RUN_DIR` is required for integration
  checks; a run without it explicitly skips those tests.
- Native QUICK `nr-handover-target` suite PASS via `./test.py -n ... --jobs=1`.
  This regression suite is not an A3/A2A4 comparative experiment.
- Fresh D1 45 s regression PASS; **all 12 raw CSVs byte-identical** to the D1
  release. All 49 protected D1/source/documentation/release files unchanged.
  Evidence lives under `research-backups/d2-baseline-20261030/` in ns-3.

| UE | TX | RX | Undelivered at 90 s | UE EndOk | gNB EndOk |
|---|---:|---:|---:|---:|---:|
|0|8800|8103|697|2|2|
|1|8800|4137|4663|6|5|
|2|8800|8782|18|0|0|
|3|8800|8800|0|0|0|
|4|8800|8800|0|0|0|

Aggregate TX 44,000 / RX 38,622 / undelivered 5,378. Undelivered is end-of-run
accounting, not a claim that every packet is permanently dropped or HO-caused.

The blocker is UE1 / IMSI4 / attempt6, cell3 -> cell2:
UE start 49.542171427 s; UE EndOk 49.544035713 s; native target
HandoverFailureJoining **49.740064459 s**, RNTI5. No gNB EndOk is present.
At 90.000000001 s the UE still reports CONNECTED_NORMALLY on cell2/RNTI5,
but cell2 has no corresponding UeManager. This is an observed native joining
timeout, not a logger-inferred event. The underlying reason the target did not
complete joining (radio/SRB delivery or another mechanism) remains unverified.
No power/filter/channel/policy changes were made to suppress this outcome.

Each full run produced about 72.85 MB raw data and used about 152 MiB peak RSS.
Wall times were 92.1 and 198.7 s; analysis/tests overlapped and machine load was
not controlled, so these times are resource-budget evidence, not a comparative
performance result. Runner bounds: 1536 MiB virtual address space, 600 CPU s,
660 wall s. Runs were sequential; source/binary/shared-library hashes stayed
unchanged during each run. D3 population scaling remains inappropriate now.

## Reproduction in the existing project

Copy only the three D2 simulation files from `simulation/` to a compatible
ns-3 checkout's `scratch/`. Keep D1 files and outputs intact. From ns-3 root:

```bash
./ns3 build dt-d2-simulation -j 1
.venv-analysis/bin/python -B analysis/run_d2.py --sim-time=6 --turn-time=2 --output-dir=dt-output/d2-smoke-new
.venv-analysis/bin/python -B analysis/phase_d2.py --run-dir=dt-output/d2-smoke-new --output-dir=dt-output/d2-smoke-report-new
.venv-analysis/bin/python -B analysis/run_d2.py --output-dir=dt-output/d2-full-a-new
.venv-analysis/bin/python -B analysis/run_d2.py --output-dir=dt-output/d2-full-b-new
.venv-analysis/bin/python -B analysis/phase_d2.py --diagnostic --run-dir=dt-output/d2-full-a-new --compare-run=dt-output/d2-full-b-new --output-dir=dt-output/d2-diagnostic-new
D2_RUN_DIR=dt-output/d2-smoke-new .venv-analysis/bin/python -B -m unittest discover -s analysis -p 'test_phase_*.py'
```

Full run commands currently return 1 and diagnostic analysis returns 2, as
explained above. Run them separately; do not use a success-only shell chain
that would silently skip the diagnostic after the expected producer failure.
When running the standalone project's runner, pass `--ns3-root` explicitly;
analysis accepts external `--run-dir` paths. Existing `phase_c22_sinr.py` is the
unchanged shared SINR parser; D2 never calls or edits the D1 analyzer.
Use fresh output paths every time. No new dependencies were installed.
Recorded local paths: `dt-output/d2-20261030-smoke05`,
`dt-output/d2-20261030-full02`, `dt-output/d2-20261030-full03`,
`dt-output/d2-20261030-repeat-diagnostic` in the ns-3 checkout.
Raw datasets remain external to the standalone project; the diagnostic JSON
is copied into `docs/PHASE_D2_VALIDATION.json`.

## Next required work, in order

1. Isolate the native UE1 attempt6 joining timeout with SRB/RLC/MAC/PHY delivery
   evidence and a minimal reproducer. Preserve the failed baseline and all raw
   event identities. Do not change A3/power/TTT or select a favorable seed to
   make the release gate green.
2. Validate actual gNB context membership over time alongside the existing
   **UE-reported** connected-population series; a UE's connected flag alone
   does not prove target-side context/admission after a failed joining.
3. Resolve or explicitly support failure/recovery in a scoped follow-up, then
   rerun strict full-gate validation and same-seed repeatability. Only after
   that freeze a D2 release. Current diagnostic mode is not that release.
4. Add predeclared ping-pong/recovery metrics and broader independent seeds as
   required by the D0 roadmap; actual queue demand, direction-specific load,
   standardized HIT, counterfactual QoS, graph datasets and AI remain absent.
5. Run the deferred controlled A3/A2A4 comparison only after this foundation
   gate is resolved. Preserve the policy comparison design above.

## CSV schemas

The canonical exact raw headers are `analysis/d2_schemas.json`. The analyzer
rejects unknown/missing raw CSVs, reordered/extra/missing columns and malformed
row lengths. Empty RRC/failure datasets are allowed when no events occur;
required registry/mobility/PRB/radio/flow/packet coverage is checked separately.
`radio_settings_v3.csv` is an end-of-run effective-attribute snapshot. Origins
are explicit versus library_default; gNB scope uses cell ID, gNB_array scope
uses gNB index, UE scopes use UE index, channel/condition/fading use BWP index.
It records actual antenna array dimensions/elements, PHY power/noise/pattern,
L1/L3 filtering, propagation/condition/fading types and update settings.

- `x2_registry_v3.csv`: `source_cell_id,target_cell_id`
- `trace_registry_v3.csv`: `scope,node_id,ue_id,imsi,cell_id,bwp_id,trace,source`
- `prb_slots_v3.csv`: `time_s,slot_index,cell_id,bwp_id,active_rntis,allocated_prb_symbols,data_symbols,available_prbs,available_symbols,full_slot_symbols,source`
- `cell_ingress_v3.csv`: `time_s,cell_id,ue_id,imsi,flow_id,sequence,tx_time_s,udp_bytes,source`
- `run_config_v3.csv`: `scenario,duration_s,sampling_ms,seed,run,enable_handover,carrier_hz,bandwidth_hz,hysteresis_db,ttt_ms,traffic_interval_ms,udp_bytes,turn_s,stop_motion_s`
- `rrc_measurements_v3.csv`: `time_s,ue_id,imsi,serving_cell_id,rnti,meas_id,serving_rsrp_ie,neighbour_cell_id,neighbour_rsrp_ie`
- `ue_registry_v3.csv`: `ue_id,imsi,node_id,ipv4,flow_id,destination_port,initial_cell_id,x0_m,y0_m,z0_m,vx_mps,vy_mps,vz_mps`
- `cell_registry_v3.csv`: `gnb_id,node_id,cell_id,bwp_id,x_m,y_m,z_m`
- `udp_packets_v3.csv`: `time_s,ue_id,imsi,flow_id,event,sequence,tx_time_s,udp_bytes,cell_id,rnti,valid`
- `handover_events_v3.csv`: `time_s,ue_id,imsi,attempt_id,event,source_cell_id,target_cell_id,rnti`
- `udp_summary_v3.csv`: `ue_id,imsi,tx_packets,rx_packets,rx_unique,rx_bytes,lost_unique,final_cell_id,ho_starts,ho_ends,ho_errors,gnb_ends,active_attempt`
- `flow_monitor_v3.csv`: `flow_monitor_id,ue_id,source_ip,destination_ip,source_port,destination_port,protocol,tx_packets,rx_packets,tx_ip_bytes,rx_ip_bytes,lost_packets,unresolved_packets`
- `ue_mobility_v3.csv`: `time_s,ue_id,imsi,x_m,y_m,z_m,vx_mps,vy_mps,vz_mps,speed_mps,valid`
- `serving_cells_v3.csv`: `time_s,ue_id,imsi,cell_id,rnti,rrc_state,connected`
- `radio_measurements.csv`: `time_ns,time_s,ue_id,imsi,rnti,bwp_id,serving_cell_id,measured_cell_id,is_serving,metric,value,unit,source`
- `sinr_measurements.csv`: `time_ns,time_s,ue_id,imsi,rnti,cell_id,bwp_id,channel_type,sinr_linear,sinr_db,valid,status,source`
- `radio_settings_v3.csv`: `scope,id,object_type,attribute,value,origin`
- `gnb_failures_v3.csv`: `time_s,ue_id,imsi,cell_id,rnti,event`
- `gnb_context_v3.csv`: `time_s,ue_id,imsi,cell_id,rnti,ue_rrc_state,gnb_context_present,gnb_imsi,gnb_rrc_state,pending_gnb_completions`
