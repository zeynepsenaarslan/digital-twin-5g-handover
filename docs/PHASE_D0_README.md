# Phase D0: paper, metric and Digital Twin readiness audit

Date: 2026-10-19. **Documentation audit complete; simulation and results unchanged. No commit or push authorized for this phase.** Source baseline: standalone commit `68053347939a8ba09e9c0c0ffc2c4fa8c13b37e3`. The original scratch simulation equals the repository copy byte-for-byte.

## Evidence and scope

Read the complete locally supplied 10-page manuscript and inspected TableII p5, TableIII p7, TableIV p8, TableV p9, Figure6 p8, definitions/Eqs1–13 pp4–6, Algorithms1–3 pp6–7 and evaluation §V pp6–9. Figure6 and Eq10–13/Algorithm1 page were also rendered and visually checked. Tables use PDF page numbers. PDF identity: SHA-256 `7c9a7252a23485e817ad32539100a68e93e1cc320634fc86a5a7a68a8e97efd2`. Its LaTeX template publication header is not a verified journal/version marker.

The PDF's redistribution rights have **not** been verified. It and its Zone.Identifier sidecar remain local, untracked, and unstaged. Public links in existing README are not a redistribution grant. Only the five new documentation files are intended for staging; never use `git add .` while `references/` is untracked. No paper PDF, rendered page or extracted full text is included in these documents' commit candidates. Source-license scope and third-party notices are unchanged.

Read simulation loggers/setup/validation, C1 analyzer, C2.1 validator, C2.2 parser/validator, plotting pipeline, all three Python test files, current README/reproduction/portability/license notes and recorded C2.2 validation. Installed NR helper defaults and model-derived RSRQ implementation were inspected read-only. No library source changes, experimental reruns, model training or algorithm tuning occurred.

## Findings

- Paper TableIII: 12 gNBs,360 UEs,1000×1000 m²,300 s/30 ms, Matérn-II deployment, bounded stochastic waypoint [1,20] m/s, mixed FR1/FR2 .7/.3, full-buffer UDP. Current implementation: deterministic2/1 nodes, constant5 m/s,3.5 GHz/20 MHz UMa,43 dBm numerology1,30/45 s, sparse fixed-rate UDP. Only mobility sampling interval matches30 ms.
- Paper uses UE–gNB pair traces, external policy replay, AMF/NG what-if validation and OAI signalling evaluation. Current program uses native real-RRC A3-RSRP X2 over EPC. It is not full5G SA, NGAP validation or DT-WIG.
- TableII requires13 columns for each UE/gNB. We have positions/speed, reported serving/neighbour PHY RSRP, model-derived RSRQ, current-cell DATA/CONTROL SINR, application delay/variation/goodput/loss and actual RRC events. No PRB utilization, cell load time series, per-cell QoS, candidate risk, graph histories, counterfactual QoS or model outputs exist.
- SINR is a useful project extension; it is absent from the paper's TableII. RSRP PHY dBm differs from quantized RRC reports; DATA/CONTROL SINR averaging differs; model-derived RSRQ is not independently validated standards-compliant RSRQ.
- TableII gNB2–6 lacks five-slot semantics. Algorithm3 line6 confuses gNB packet-loss column13 with UE serving-load column13. Exact H,L,epsilon and several radio/metric/timing/split contracts are unspecified. These block a claim of exact reproduction; they do not block a clearly labeled small-scale research extension.
- Figure6 offers qualitative paired-policy evidence without exact labels/error bars/raw data, and its RSS bars do not exactly match TableV. TableIV is runtime comparison, not MAE/RMSE table. No paper performance numbers are represented as project measurements.

## Documentation map

- [PAPER_PARAMETER_AUDIT.md](PAPER_PARAMETER_AUDIT.md): paper provenance, per-parameter source, current value, gaps, equations, all TableIV/V values and ambiguities.
- [METRIC_DEFINITIONS.md](METRIC_DEFINITIONS.md): formulas, units, intervals, denominators, raw data, implementation status and limits; paper statements versus proposed operational definitions.
- [DT_FEATURE_SCHEMA.md](DT_FEATURE_SCHEMA.md): complete TableII mapping, proposed identities/edges/time/missingness and leakage safeguards.
- [RESEARCH_EXTENSIONS.md](RESEARCH_EXTENSIONS.md): seven proposed metrics, feasibility, confounders and controlled experiments.

## Safe staged transition (plan only)

| Stage | Scope / gate | Measurements that must be resolved |
|---|---|---|
| D1 | 2 gNB /3 UE; first preserve old1-UE mode and regression; modest traffic, no AI | Per-UE mobility/IMSI registry; per-flow TX/RX with unique stream+sequence; per-UE attachment and attempt state; per-link PHY identity; aggregate counters equal sum of keyed flows |
| D2 | 3 gNB /5 UE; multiple targets and repeatable return mobility | Per-cell attachment population, verified PRB allocation/utilization hooks, cell-attributed QoS; target and neighbour ranking masks; ping-pong/recovery accounting and multiple simultaneous attempts |
| D3 | Progressive counts/durations toward12/360/300 s only after RAM/runtime profiling | Repeated independent topology/mobility seeds; explicit saturation/load and FR1/FR2 configuration; confidence intervals; candidate/execution timing; layer-specific signalling if feasible |
| D4 | Graph dataset generation; no training prerequisite | Causal snapshot grid, documented load, verified units, graph relation types, action/branch provenance, history/target horizons, split-by-realization before windows |
| D5 | Dataset validation and release gate | No future/counterfactual leakage, masks/age, key integrity, split disjointness, label coverage/censoring, reproducibility and stress tests; only then model planning |

D3 must not jump directly to360 UEs on this low-RAM machine. Profile memory/wall time/output size at each increment with a fixed seed set; abort on configured resource budget. Use sequential or one-job builds/runs and avoid all-pairs concurrent counterfactual jobs. Staggered smaller jobs are P, not a claim of computational equivalence to the paper's multithreaded generation. Control offered load separately from population: scaling traffic, topology and scheduler simultaneously prevents attribution.

## D1 readiness checklist

- [ ] Obtain approval for a separate D1 implementation; D0 changes documentation only.
- [ ] Parameterize UE count without breaking exact1-UE behavior; keep an independent reference run.
- [ ] Define stable registry (UE index,IMSI,node/device,cell,BWP) and time-varying RNTI mapping.
- [ ] Replace singleton attachment/HO state and fixed source/target assumptions with keyed attempt records; capture all terminal/incomplete states.
- [ ] Install applications/routes and packet callbacks for every UE; key successful TX and RX by flow/UE+sequence, not global sequence alone.
- [ ] Make C1 loss accounting and HO phase joins per-flow/per-UE; preserve aggregate conservation and censoring rules.
- [ ] Generalize validators/plots beyond UE0/IMSI2/BWP0/cells1–2. Existing native radio connection loops alone do not establish multi-UE safety.
- [ ] Validate3-UE identities, simultaneous events, legitimate equal timestamps, cell changes and initial attachment; verify no duplicate trace connections.
- [ ] Inspect native load/PRB trace APIs before promising cell-load features; freeze aggregation denominators.
- [ ] Record runtime/RAM/output budget, independent RNG stream policy, run manifest and immutable source/version/config hashes.

D1 is **ready for design review, not ready to claim paper-scale reproduction or train DT-WIG**. Highest-priority coding order: identity/flow schema, backward-compatible scenario parameterization, per-UE apps and HO state, offline keyed analysis, validators, then carefully scoped PRB/load instrumentation. No proposed feature is implemented by this audit.

## Validation and limits

Initial D0 checks recorded exactly five new Markdown documents staged, reference PDF absent from the index, protected source/analysis/figures/PDF/license/notices and Git remote configurations unchanged by hash, source-manifest validity, resolving document links and all19 existing Python tests passing. Historical C2.2 evidence remains18,864 SINR samples (4,419 DATA /14,445 CONTROL), TX4300/RX4299, one missing sequence3974, six legacy CSVs byte-identical to the prior reference. No new simulation build or run is claimed for a documentation-only phase.

Final review limitation: the earlier temporary historical-output hash inventories are no longer available, so unchanged contents of every historical experiment file cannot be independently re-established in the final review. Six legacy CSVs were re-compared successfully to the preserved reference, six input hashes in the plot manifest matched, and SINR validation again passed for18,864 samples. This is a limitation of available evidence, not a detected data change. No fresh simulation run or comprehensive historical-output hash audit is claimed.

The existing UE RRC interval1.864286 ms and consecutive packet reception gap20.5 ms are not standardized HIT; delay variation is not RFC3550 jitter; application goodput is not PHY/MAC throughput. One UE and seed do not provide fairness/tail/robustness evidence. Exact paper metric replication is limited by missing operational definitions, version identity and unavailable underlying data/model/OAI setup.

PDF extraction/rendering required pypdf6.21.1 and PyMuPDF2.0 in an isolated `/tmp/d0-pdf-venv`; system Python and repository requirements were not modified. Rendered pages/extracted text remain temporary local working material. No new dependencies are required to use these Markdown documents.

Before publication, review the five staged files, source-version ambiguities and proposed definitions; request explicit approval for commit/push. Neither publication nor simulation changes are part of D0.
