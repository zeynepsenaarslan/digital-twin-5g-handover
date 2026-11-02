# Phase D1: deterministic 2-gNB / 3-UE foundation

D1 implements multi-UE simulation and measured identity/accounting only. It does not implement DT-WIG, AI, graph generation, NGAP, AMF validation or new handover policy. D0 publication was checked with `git ls-remote origin refs/heads/main`: local and remote main were `d41e1266d2d4f9d31bb74518eba1cc808678c1dc` before work. These D1 changes are prepared for review only; no commit/push.

## Before-change evidence

The original working checkout already had a modified `.gitignore` and untracked research/analysis/output files; these were preserved. Standalone had only untracked `references/`. The persistent baseline is `research-backups/d1-baseline-20261019-204330/`: source backup and `snapshot.json` with136 SHA-256 entries (original simulation, all134 pre-existing output files, upstream Git config). Rechecking the135 entries other than the intentionally edited simulation passed. No upstream library source or Git configuration/remote was modified. Old simulation results were not overwritten. The reference PDF and Zone.Identifier are not distribution candidates.

## Scenario and compatibility

`--scenario=legacy` is default. All original mobility flags, behavior, CSV schemas and validation code execute unchanged there. The new header `dt-d1-support.h` must sit beside `dt-handover-simulation.cc`. It is a simulation helper, not a new upstream module. The main source adds only its include, selector and checked branch. D1 rejects nondefault legacy topology/mobility flags instead of silently ignoring them. D1 supports duration, samplingMs, seed/run, enableHandover and outputDir; it requires a fresh output directory.

D1 sites: `(0,0,25)` and `(300,0,25)` m. Same3.5 GHz/20 MHz single BWP, UMa channel and installed defaults, ideal DirectPath beamforming, numerology1,43 dBm gNB power. `--enableHandover=1` selects the same real-RRC `NrA3RsrpHandoverAlgorithm`, hysteresis1.5 dB, TTT128 ms, X2/EPC. No radio/scheduler/channel parameters were tuned to force expected results. Seed/run1/1. Determinism here means repeated same configuration/build/seed, not invariance across ns-3 versions or UE population.

| UE index | Actual IMSI / IPv4 | Start m | Velocity m/s | Initial cell | Geometry-only expectation, not an asserted outcome |
|---|---|---|---|---|---|
|0|2 /7.0.0.2|(20,20,1.5)|(5,0,0)|1|Moves toward cell2; may trigger A3 |
|1|3 /7.0.0.3|(280,−20,1.5)|(−5,0,0)|2|Moves toward cell1; may trigger A3 |
|2|4 /7.0.0.4|(25,60,1.5)|(0,0,0)|1|Stationary control; no forced HO |

Each UE receives its own downlink512-byte UDP datagrams every10 ms,1 to44 s in the45 s run; drain1 s. Ports1234/1235/1236, ephemeral source ports49153/49154/49155 in this run. Application flow IDs0/1/2 differ from native FlowMonitor IDs1/2/3. Bindings, tuple mapping and counters are checked rather than assuming these numeric sequences are permanent identifiers.

## Why the new sender and keyed loggers exist

Installed `src/applications/model/udp-client.cc:201` emits Tx before SeqTsHeader addition and before checking Send success. It cannot directly supply a successful-send sequence log. D1's small `Sender` creates the same-size SeqTsHeader UDP payload and records a TX event only after Socket::Send accepts512 bytes; failed sends abort with no fabricated TX. Legacy still uses its original UdpClient. No cross-mode equality is claimed between custom and native senders under changed multi-UE radio conditions.

`State` binds a specific UE/device/IMSI/flow and owns its counters and current handover attempt. RNTI is recorded at each event; it is not a global key. At attachment, UE0 and UE1 both have RNTI1 in different cells, which demonstrates why IMSI/flow keys matter. `Dispatcher` routes shared gNB RRC callbacks by IMSI; UE callbacks are bound per state, and UE-local attempt IDs allow repeated handovers, with a separate pending gNB acknowledgement registry. `Sampler` reads all three position/velocity/RRC states. Existing radio/SINR loggers connect once per UE/BWP using bound UE identity; no Genie callback or synthetic neighbour measurements are used.

FlowMonitor is installed only on remote host and UE endpoints in D1, as in the installed NR example. Classifier destination IP/UDP port plus common remote source map each UDP five-tuple to its actual UE. IPv4 counts are checked against application TX/RX; recorded IP bytes are540 per unfragmented512-byte UDP datagram (20 IPv4 +8 UDP bytes). They are not PHY throughput.

## CSV contract

D1 uses new versioned filenames to prevent old single-UE tools from silently interpreting aggregates. The passive radio and SINR schemas were already UE-keyed and remain unchanged.

| File | Main columns / scope |
|---|---|
|run_config_v2.csv|scenario,duration_s,sampling_ms,seed,run,enable_handover and declared radio/traffic constants |
|cell_registry_v2.csv|gnb_id,node_id,cell_id,bwp_id,x/y/z_m |
|ue_registry_v2.csv|ue_id,imsi,node_id,ipv4,flow_id,destination_port,initial_cell_id,initial position and velocity |
|ue_mobility_v2.csv|time_s,ue_id,imsi,x/y/z_m,vx/vy/vz_mps,speed_mps,valid |
|serving_cells_v2.csv|time_s,ue_id,imsi,cell_id,rnti,rrc_state,connected; periodic native RRC state, not a fresh PHY report |
|handover_events_v2.csv|time_s,ue_id,imsi,attempt_id,event,source_cell_id,target_cell_id,rnti; real attachment/UE start/end/error/gNB end |
|rrc_measurements_v2.csv|time_s,ue_id,imsi,serving_cell_id,rnti,meas_id,serving_rsrp_ie,neighbour_cell_id,neighbour_rsrp_ie; quantized IE values, **not dBm** |
|udp_packets_v2.csv|time_s,ue_id,imsi,flow_id,event(TX/RX),sequence,tx_time_s,udp_bytes,instantaneous RRC cell_id/rnti,valid |
|udp_summary_v2.csv|per-UE actual TX,RX,unique RX,bytes,undelivered count,final cell,HO counters,incomplete flag |
|flow_monitor_v2.csv|native flow ID,UE,five-tuple,IP packet/byte counts,classified lost and unresolved counts |
|radio_measurements.csv|unchanged C2.1 schema; full UE/BWP/current+measured cell identity,role,metric,value,unit,source |
|sinr_measurements.csv|unchanged C2.2 schema; separate DATA/CONTROL,linear power ratio,dB,valid/status,source |

`time_s` is simulator time to9 decimal places, read as exact ns by Python. Mobility and serving samples cover0–45 s inclusive every30 ms:1501 rows per UE. RRC/packet/PHY events are asynchronous. First sampled RRC state may precede attachment and is marked connected=0. Physical RSRP is dBm; RSRQ remains model-derived dB. SINR is modeled linear power ratio and safe10log10 conversion, not hardware measurement. Invalid SINR retains raw/status with missing dB; no invalid SINR rows occurred in the recorded run. Quantized RRC values remain a separate CSV.

The D1 analyzer creates `qos_packets_v2.csv` (delay, absolute consecutive delay variation, explicit delay_valid/variation_valid; first variation missing) and `qos_timeseries_v2.csv` (per-UE100 ms windows, bytes/goodput, received-only delay mean and delay_valid). Empty windows have actual zero bytes/goodput and missing delay. Rates use8*received UDP bytes/(duration_s*10^6) Mbit/s;512 bytes include12-byte SeqTsHeader and exclude UDP/IP/link headers. Delay variation is not RFC3550 jitter. HO event durations and report-to-UE-start gaps are not standardized HIT or direct policy-decision timestamps.

## Build/run commands and actual output paths

Working checkout commands (fresh output directories required on subsequent runs):

```bash
./ns3 build dt-handover-simulation -j 1
./ns3 run 'dt-handover-simulation --simTime=30 --outputDir=dt-output/phase-d1-20261019-204330-legacy30' --no-build
./ns3 run 'dt-handover-simulation --enableHandover=1 --simTime=45 --outputDir=dt-output/phase-d1-20261019-204330-release-legacy45' --no-build
./ns3 run 'dt-handover-simulation --scenario=d1 --enableHandover=1 --simTime=45 --outputDir=dt-output/phase-d1-20261019-204330-release-multi45' --no-build
.venv-analysis/bin/python -B analysis/phase_d1.py --run-dir dt-output/phase-d1-20261019-204330-release-multi45 --output-dir dt-output/phase-d1-20261019-204330-release-report
.venv-analysis/bin/python -B -m unittest discover -s analysis -p 'test_phase_*.py' -v
```

The actual local build used `ninja -C cmake-cache -j 1 scratch/CMakeFiles/scratch_dt-handover-simulation.dir/dt-handover-simulation.cc.o` and the CMake-generated linker command from `ninja -C cmake-cache -t commands scratch_dt-handover-simulation`. This compiled the new helper and linked the simulation successfully; no full all-target/module-test rebuild is claimed. Initial Packet method/type name collision was resolved with explicit `ns3::Packet`. Initial offline RRC check incorrectly assumed a sub-ms report/start gap; actual2.1–2.4 ms gaps led to chronological source/target/UE-local report pairing, with no simulation parameter changes. Build output and tests are preserved under the new backup evidence directory. No new packages were installed for D1; existing Matplotlib3.11.2/Agg was used.

For the standalone repository, integrate **both** simulation files into a separate compatible ns-3 scratch location, run there, and invoke `analysis/phase_d1.py` with external data paths. Old C1/C2.1 single-UE validators and C2.3 plots remain for legacy outputs; do not pass the v2 producer to them. D1 has its own validation/plots. Replace the dated output paths to rerun; existing files are refused.

## Observed results: no enforced target outcomes

| UE | TX | RX / bytes | Undelivered at45 s | PDR | Mean delay ms | Mean absolute variation ms | Active-window goodput Mbps | HO / final cell |
|---|---:|---|---:|---:|---:|---:|---:|---|
|0|4300|4113 /2105856|187|95.651163%|22.111459|3.577890|.391787163|2 /1|
|1|4300|4189 /2144768|111|97.418605%|13.999190|2.250145|.399026605|0 /2|
|2|4300|4300 /2201600|0|100%|2.750928|.038264|.409600000|0 /1|

Aggregate: TX12900,RX12602,bytes6452224,undelivered298. No observed duplicate application receptions. Per-UE initial attachment, final connected RRC state and application/FlowMonitor packet counts agree.

UE0 actual events:

| Attempt | Source→target | gNB received A3 RRC report | UE start | UE EndOk | gNB EndOk |
|---|---|---:|---:|---:|---:|
|1|1→2|30.140064281|30.142457139|30.144035713|30.148564480|
|2|2→1|34.532564281|34.534671427|34.536535713|34.548564480|

The RRC neighbour/serving RSRP IE pairs were70/68 and71/69. UE0 RNTI changed1→2→3; UE1 stayed RNTI1/cell2. These are genuine measured A3-RSRP events; SINR did not trigger them. Both SINR channels and received traffic continue after both completions. UE1's lack of handover is an observation, not a failed identity check. A return exists, but no standardized ping-pong rate is claimed without a declared observation window/denominator.

The final PHY RSRP reports support the observed serving choices: UE0 around44.8 s reports cell1 about−69.29 dBm vs cell2−85.84; UE1 reports cell2−88.67 vs cell1−92.42. Geographic proximity alone does not predict the beamformed/interference-aware, filtered native measurement ordering. Multiple UEs change scheduling/beams/interference and RNG consumption; legacy and multi-UE results are not paired causal comparisons. Exact attribution of these large radio differences to a specific mechanism needs further controlled instrumentation, not an assumed explanation or tuning.

Loss investigation: UE0 missing TX timestamps span30.14–43.94 s; UE1 span28.32–42.40 s. Many are well after HO, and UE1 has no HO, so the298 missing packets cannot all be called handover losses. FlowMonitor reports15 classified lost+172 unresolved for UE0,12+99 for UE1,0+0 for UE2; each sum equals application's end-of-run missing count. Installed FlowMonitor default MaxPerHopDelay is10 s (`src/flow-monitor/model/flow-monitor.cc:36`), longer than the1 s final drain. Unresolved is deliberately separate: no claim all outstanding packets are permanently dropped or that the drop layer/cause is known. RLC/MAC drop/retransmission/queue diagnosis and extended-drain controls are deferred. D1 PASS validates correct identities/accounting/events, **not excellent QoS or paper performance reproduction**.

## Validation and plots

- Legacy30: PhaseA/B1/B2 PASS,1001 mobility samples; six pre-C2.2 CSVs byte-identical to preserved C2.1 baseline30.
- Legacy45 with final executable: PhaseA/B1/B2/B3 PASS,1501 samples; all seven CSVs including SINR byte-identical to preserved C2.2 run. TX4300/RX4299 and HO timestamps unchanged.
- D1 repeated same-seed run after adding passive RRC evidence: all10 common CSV files byte-identical; added config/report files do not alter previous observations. This is repeatability evidence, not a multi-seed reliability result.
- D1 validator PASS: stable IDs/IPs, distinct flows, successful TX/RX joins, nonnegative exact timestamps, analytical trajectories, complete serving histories, source/target/IMSI/attempt matching, actual preceding RRC reports, units, no exact duplicate PHY records, post-HO target SINR and per-UE/IP/application totals.
-2700 PHY RSRP/RSRQ rows (900 per UE);74855 SINR rows. DATA counts8292/9264/4305; CONTROL18133/16851/18010. Each UE has both channels; no invalid SINR rows. Only actual reported neighbour measurements are stored.
-31 Python tests PASS: existing19 plus12 new tests for cross-UE IMSI/flow corruption, same sequence across flows, duplicate callbacks, wrong TX timestamps/counters, simultaneous local attempts, wrong targets, missing/repeated terminal events, delayed gNB acknowledgement identity and invalid times.
- Five figure families saved as300-DPI PNG and SVG: d1_mobility, d1_radio, d1_sinr, d1_qos,d1_serving. Red dashed/black dotted markers are actual UE start/end times. PHY plots scatter actual samples without interpolation. Dense SINR SVG points are rasterized, axes/labels vector. Serving plot is explicitly a sampled-state step display, not inferred exact transition timing. Selected PNGs can be copied to the standalone repository; raw CSVs remain external.
- Input SHA-256s in validation.json are checked again after plotting. Original135 protected prior-output/config hashes unchanged. Source backup remains available.

## Remaining D2 / D4 gaps and risks

Per-cell PRB utilization, scheduler load/queues, cell QoS, all-pairs target counterfactual measurements, graph snapshots and leakage-safe dataset labels remain absent. Only2 cells permit one reported neighbour; missing top-four slots must not be fabricated. No new PHY/MAC trace hooks were needed. Native radio filtering/beam/scheduling semantics require further controlled study before scaling or using observed QoS for DT training. Packet cell attribution is instantaneous RRC state at the event, not proven bearer delivery cell during forwarding. Failed/incomplete attempts remain visible and cause validation failure rather than an invented completion; more failure-recovery scenarios are future tests. Pending gNB acknowledgements are keyed by UE IMSI plus target cell/RNTI and retain the original attempt/source, so a delayed acknowledgement does not borrow a newer attempt identity. Dedicated failure/recovery and delayed-acknowledgement stress scenarios remain follow-up coverage.

No standardized HIT, RFC3550 jitter, full5G SA, AMF validation, paper-scale reproduction or causal performance benefit is claimed. Loss diagnosis is incomplete. One seed/run and deterministic paths cannot establish robustness; memory/time/output budgets and independent RNG-stream controls are needed for D2/D3. The reference paper's Algorithm3 column inconsistency and ambiguous features remain documented by D0; D1 does not silently repair them.
