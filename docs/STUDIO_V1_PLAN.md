# 5G Simulation Studio V1 implementation plan

The next development priority is **Studio V1, not D3**. Implement it after these
preparation commits on a separate branch, proposed name `feature/studio-v1`, based
on `review/d2-handover-studio-prep`. This document adds no UI implementation.
V1 reads existing D2 CSVs and does not change or launch the simulation engine.
D2 remains incomplete; the viewer must represent both healthy and failed runs.

## Data sources and truthful presentation

The exact 19 raw schemas are versioned in `analysis/d2_schemas.json`. Keep these
headers unchanged. Import the existing validated analysis semantics; do not create
a second interpretation of identity, handover completion or packet accounting.
Six derived CSVs are produced by `analysis/phase_d2.py`. Store visual caches outside
raw evidence and key them by file hashes and parser version.

| View | CSVs and essential fields | Semantics |
| --- | --- | --- |
| Static 3-gNB map | cell_registry_v3: gnb_id,cell_id,bwp_id,x_m,y_m,z_m | Local meters, no invented geographic coordinates |
| Moving 5-UE topology | ue_registry_v3: ue_id,imsi,node_id,initial_cell_id; ue_mobility_v3: time_s,ue_id,x_m,y_m,z_m,speed_mps,valid | Slider follows recorded sample epochs; display sample time and missing-data gaps |
| Serving links | serving_cells_v3: time_s,ue_id,cell_id,rnti,rrc_state,connected | UE-reported serving cell, not proof of target context membership |
| Handover timeline | handover_events_v3: time_s,ue_id,imsi,attempt_id,event,source_cell_id,target_cell_id,rnti | Separate UE start/EndOk and gNB EndOk; preserve pending attempts |
| Failure markers | gnb_failures_v3: time_s,ue_id,imsi,cell_id,rnti,event; gnb_context_v3: final presence/state/pending | Explicit red failure markers and final missing-context warning; never synthesize successful completion |
| RSRP | radio_measurements: time_ns,ue_id,serving_cell_id,measured_cell_id,is_serving,metric,value,unit | Native PHY dBm; actual serving and neighbour observations only; RRC IE is a distinct quantity |
| SINR | sinr_measurements: time_ns,ue_id,cell_id,channel_type,sinr_linear,sinr_db,valid,status | Separate DATA and CONTROL; invalid/missing observations remain gaps |
| PRB | prb_slots_v3: cell_id,bwp_id,slot_index,allocated_prb_symbols,available_prbs,available_symbols; derived cell_prb_v3: window_start_s,allocation_fraction,valid | Cell-level UL+DL DATA/MSG3 PRB-symbol allocation; not per-UE load, DL-only load or queue demand; bootstrap window masked |
| QoS | udp_packets_v3,cell_ingress_v3,flow_monitor_v3; derived qos_packets_v3 and cell_qos_v3 | Goodput, received-only delay and observed delivery; S1-U ingress-cell cohorts; unresolved packets are not proven permanent drops |
| Profile and provenance | run_config_v3,radio_settings_v3,radio_profile.json,run_manifest.json,validation.json | Show effective UE/gNB power, seed/run, source hashes, analysis status and evidence scope |

RNTI is cell-local. Join by UE/IMSI plus cell/BWP/time; join handover attempts by
UE-local attempt_id and recorded lifecycle. A UE EndOk alone is insufficient.
The final gNB context snapshot cannot provide a time series of actual admission.
No standardized HIT, per-UE PRB demand, causal HO QoS loss or counterfactual metric
is available; leave unsupported panels absent or explicitly unavailable.

## Proposed repository layout

```text
studio/
  app.py
  data/
    contracts.py
    catalog.py
    loader.py
  domain/
    timeline.py
    metrics.py
  views/
    topology.py
    events.py
    radio.py
    qos.py
  config/
    profiles.json
tests/studio/
docs/STUDIO_V1_PLAN.md
```

Use Streamlit for controls/state and Plotly for a Cartesian topology and linked
time-series panels. Keep optional UI dependencies separate from the existing
analysis requirements and pin tested versions when implementation begins.
No packages are installed by this preparation.

## Implementation sequence and acceptance

1. Create the separate Studio branch from the reviewed preparation branch.
   Establish a local allowlisted run catalog outside version control; never
   bundle the large evidence CSVs in the UI repository.
2. Implement a read-only loader with exact schema/version, units, identity,
   finite-time and provenance checks. Healthy PASS/VALIDATED_SINGLE_RUN and
   diagnostic BLOCKED_NATIVE_HANDOVER must remain visibly distinct. Handle an
   absent old radio_profile.json as the documented inherited 2 dBm profile only
   through the existing analyzer contract, not a generic guessed default.
3. Build the metre-coordinate topology using registry positions, recorded
   mobility epochs, UE/cell filters, play/pause and a time slider. Mark the time
   of each actual sample; do not interpolate metric values or invent motion
   measurements. Static gNBs and a UE's observed serving links share the view.
4. Add an event table and source/target HO markers. Failed joins remain visible
   even when a UE EndOk exists. Show pending gNB completion and final missing
   target context separately. Empty failure CSV means no recorded failure, not
   universal failure-free behavior.
5. Add linked RSRP/SINR, cell PRB allocation and QoS panels using the validated
   derived contracts. Mask invalid/bootstrap windows; preserve denominators,
   channel types, units and ingress-cohort labels. Never zero-fill missing data.
6. Validate against the existing healthy 23 dBm full-a and historical 2 dBm failed
   datasets plus small corruption fixtures. Check timeline boundaries, filters,
   invalid windows, identity joins and failure visibility. Use selected-column
   reads and time-window display; disclose any plot downsampling. Verify raw
   evidence hashes remain unchanged after viewing.

Acceptance: 3 gNBs/5 UEs render from actual CSVs; slider/playback agrees with
sampled positions and serving cells; both HO completions and native failures are
visible; every graph has correct units/scope and preserves missing values; no
simulator invocation or write to original datasets occurs.

## Future V2 boundary

Current D2 CLI supports simTime,turnTime,samplingMs,seed,run,outputDir,ueTxPower,
diagnoseJoining and joiningPowerProbe. The runner's default root must be supplied
explicitly from this standalone repository. Current source hardcodes 3 gNBs,
5 UEs, layout/velocities, 3.5 GHz,20 MHz,UMa,numerology1,gNB43 dBm,A3 hysteresis
1.5 dB/TTT128 ms and UDP10 ms/512 bytes. Recorded shadowing/fading attributes are
not configurable UI capabilities. V1 displays them without editing them.

Only after V1, V2 may add a versioned validated Python/C++ configuration contract,
allowed shadowing/fading/frequency/BW/power/population/layout/motion combinations,
and producer/validator generalization of fixed 3/5 assumptions. Reject unsupported
combinations before execution. Use a subprocess argv list (no shell), a bounded
single-job queue, fresh run IDs, cancel/status tracking and immutable provenance;
feed results back through the same loader. The causal power probe stays outside
normal UI run profiles. V2 and D3 are not part of this commit series.
