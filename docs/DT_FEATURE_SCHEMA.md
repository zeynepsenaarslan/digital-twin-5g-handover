# Phase D0: Digital Twin feature schema audit

**E:** local manuscript TableII p5 and Eqs4–9 / Algorithms1–3 pp5–7. **P:** proposed dataset contracts below. This is a schema plan; no graph dataset, counterfactual generator, AMF or DT-WIG currently exists. The exact PDF identity is in PAPER_PARAMETER_AUDIT.md.

## Complete Table II column mapping

TableII specifies 13 columns per node. SINR is **not** a TableII column; adding it is a proposed extension, not paper reproduction.

| Node / 1-based columns | E paper feature / units | Actual data / mapping | Missing or proposed work |
|---|---|---|---|
| UE1 | node_type=1 | No graph CSV; type known from simulation | P typed registry, never infer from row order |
| UE2 | velocity, m/s | ue_mobility.csv:speed_mps, ue_id,time_s | Map UE index to IMSI; interpreting velocity as scalar speed is our implementation assumption (P), not an explicitly specified representation in TableII; vector/direction also requires an explicit proposed contract |
| UE3 | serving RSRP,dBm | radio_measurements.csv:metric=rsrp,is_serving=1,value | As-of valid report with age; not RRC encoded serving_rsrp_ie |
| UE4–7 | top-four neighbouring RSRP,dBm | measured_cell_id,is_serving=0,metric=rsrp,value | Only one neighbour possible in current two-cell setup; four actual neighbours impossible even in D2's three cells. Pad missing+mask, not zero; P rank observed causal RSRP descending, tie cell ID, store cell ID per slot |
| UE8 | serving RSRQ; paper TableII omits unit here, TableIII threshold uses dB | metric=rsrq_model_derived,unit=dB,is_serving=1 | Installed model-derived estimate; cannot claim standards calibration or paper-equivalent RSRQ |
| UE9 | throughput,Mbps | qos_timeseries.csv:goodput_mbps | Application-byte goodput is a proxy P, not verified paper throughput layer; per-UE flow attribution missing |
| UE10 | delay,ms | udp_packet_delay.csv:delay_ms; window mean_delay_ms | P completed trailing-window received-packet mean; missing when no reception |
| UE11 | jitter,ms | abs_delay_variation_ms / mean_abs_delay_variation_ms | Existing delay variation, not paper-verified jitter estimator; keep distinct field names |
| UE12 | packet loss rate,% | C1 final lost_unique_packets/final PDR | Causal online window loss needs successful TX cohorts and fixed deadline; final-run loss is future information |
| UE13 | serving cell load,% | No export | Needs explicitly defined PRB occupancy or another named load measure; do not use cell PLR |
| gNB1 | node_type=0 | gNB indices/device cell IDs in simulation | P cell registry and cell lifetime |
| gNB2–6 | average RSRP of attached UEs; five slots | UE reports can supply individual serving RSRPs | **U:** five aggregates' meanings, groups, ordering and averaging domain unspecified. Cannot fill all five with invented/repeated means. P separate named linear-power mean, pending author clarification |
| gNB7 | average RSRQ of attached UEs | UE model-derived RSRQ samples only | P explicit attachment-time set and averaging domain; not currently exported |
| gNB8 | PRB utilization,% | No export | Scheduler/PHY allocation and available-time-frequency denominator, BWP/direction needed |
| gNB9 | number of attached UEs,count | One UE's RRC events only; no attachment population time series | Reconcile complete per-cell RRC state over time, including detach/failure |
| gNB10 | cell throughput,Mbps | No per-cell export | P sum matching per-UE layer rates with explicit crossing-HO attribution |
| gNB11 | cell delay,ms | No per-cell export | P state packet-weighted or UE-weighted aggregation, both differ |
| gNB12 | cell jitter,ms | No per-cell export | Estimator and aggregation U; do not silently rename existing variation |
| gNB13 | cell packet loss rate,% | No per-cell export | Need cell-attributed TX cohorts, denominator and drain/censoring |

**Critical inconsistency:** Algorithm3 p7 line6 assigns UE13 from target gNB13, but TableII calls those load and loss respectively. Proposed correction would require an explicitly named target_load field (possibly gNB8 PRB utilization), not blindly copying column13. That correction remains P; it is not an assertion about author intent. Algorithm3 also requires target RSRQ and cell aggregates that current serving-only graph slots would not guarantee.

## Proposed identities and graph contracts (P)

Node keys: `(scenario_id, realization_id, run_id, node_type, stable_entity_id)`. Use stable UE IMSI plus explicit ue_id/ns3_node_id mapping; gNB key includes device/node and all `(cell_id,bwp_id,carrier)` mappings. RNTI is cell-local and time-varying, never a global UE key. Record association valid-from/to and attach/detach reasons. Keep integer ns timestamps as join authority and seconds for presentation.

Separate typed edge tables:

- `association`: current UE–gNB service relation; mirror directions explicitly if required by Algorithm3. A serving cell change updates both directions at recorded event boundaries under a declared effective-time convention.
- `radio_observation`: directed gNB-to-UE measured link, with measured cell and native source, observation time, report time if available, units and validity. Receiving a neighbour report does not imply service association.
- `backhaul_control`: actual X2 connectivity metadata; not a fabricated Xn or AMF edge.
- `candidate`: policy proposal UE/source/target, decision time and policy ID; absent until instrumented. A candidate is not an executed association.

Eq5 defines adjacency connectivity generally but does not specify a complete edge-type encoding or nonedge universe. Keep relation types outside a plain untyped adjacency to prevent observation edges being mistaken for associations. Full PT includes core entities (§IV-A) but TableII gives no AMF/SMF/UPF feature rows; do not invent those features as paper facts.

## Time, units and missingness (P)

Target graph grid30 ms is a planning choice aligned with TableIII, not an existing30 ms radio measurement cadence. Build each snapshot at cutoff t using records available by t only. Store `observed_at_ns`, `available_at_ns`, `age_ns`, source, validity/mask and configured maximum age. Current callbacks know emission time only; measurement-window start/end are not exported. A200 ms filtered RSRP value must not be represented as a fresh30 ms measurement. Use no future nearest-neighbour join, interpolation or backward fill. Last-known causal hold, if adopted, is explicitly flagged and expires; missing is not zero. Units: dBm for RSRP, dB for RSRQ/SINR, Mbit/s for rates, ms for delay/variation, percent for matrix loss/load, m/s for speed.

SINR extension: preserve channel_type DATA/CONTROL, source, BWP/cell, valid/status, raw linear and converted dB. It currently observes native current-cell events, not a top-four-neighbour SINR matrix. Preserve five preattachment CONTROL records with native RNTI0 as preconnection observations; do not assign fake RNTIs or attach membership from them. Event-driven samples cannot directly define time coverage below threshold without a sampling/hold model.

## Leakage controls (P)

1. Split by complete deployment/mobility realization and UE trajectory before creating overlapping history/target windows. UE–gNB alternative jobs for the same trajectory belong to one split. For within-run temporal evaluation, use chronological splits with purge spanning history+prediction horizon and measurement aggregation support.
2. Fit scalers, imputers, feature selection and thresholds only on training data. Keep missing masks. Report test results once; do not select checkpoints or risk thresholds on test outcomes.
3. Features at decision t use completed past windows only. A window ending after t, eventual packet arrival, final loss tally or future serving cell must never enter X(t).
4. Observational histories and generated candidate branches remain separate. Future target QoS, actual HO success and post-HO load are labels or evaluation outcomes, not decision-time input.
5. Counterfactual paired runs must share intended exogenous topology/mobility inputs and documented RNG streams, while marking branch/action/timing. Passive target RSRP is not a target throughput/delay ground truth. Actual future neighbour rankings must not choose today's slots.
6. Preserve labels' censoring/validity and evaluated candidate universe. Rejecting a candidate does not prove it would have failed; missing counterfactual labels remain unknown.

## Required future instrumentation

D1 needs stable identity registry, per-flow successful TX/RX logs, per-UE attempt state, complete cell association events and explicit joined measurement age. D2 can investigate attached population and allocated/available PRB counters, per-cell QoS and queues; installed APIs must be inspected before selecting hooks. D3 controls independent runs and load. D4 creates graph snapshots and action-conditioned labels only after a leakage review. D5 validates units/keys/edge symmetry when intended, split isolation, stale masks and label provenance. None of this instrumentation is added in D0.
