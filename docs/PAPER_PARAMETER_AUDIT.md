# Phase D0: paper parameter audit

Audit date: 2026-10-19. Scope: documentation only; no simulation or policy modification. Sources are the locally supplied **10-page manuscript**, `references/paper.pdf`, SHA-256 `7c9a7252a23485e817ad32539100a68e93e1cc320634fc86a5a7a68a8e97efd2`, and implementation at Git commit `68053347939a8ba09e9c0c0ffc2c4fa8c13b37e3`. Page numbers below are PDF pages, also numbered 1–10 in this copy. Its header and manuscript dates contain template placeholders; do not treat that header as verified publication metadata or assume this version is identical to a publisher's final version. Existing bibliographic records are unchanged.

Classification: **E** explicitly specified; **D** derived from an equation; **U** unspecified/ambiguous; **P** our proposed operationalization or extension. Match concerns the current implementation, not an intended future implementation. Source path `S` below means `simulation/dt-handover-simulation.cc`; the original scratch file was verified byte-identical. Python source paths refer to this repository. The supplied PDF is local research input, not approved for redistribution; it is excluded from staging.

## Deployment and measurement parameters

| Item / classification | Paper value and exact source | Current implementation / evidence | Match | Required action and reproduction implication |
|---|---|---|---|---|
| Deployment E | Matérn hard-core type II, §V-A1 pp6–7, Table III p7 | Two deterministic gNBs, S:605–640 | Mismatch | D3 needs generator and recorded minimum separation/intensity; these parameters are U in paper |
| Area E | 1000 by 1000 m², Table III p7 | No bounded area; linear UE trajectory | Mismatch | Add boundaries in a later phase; do not infer current area from 300 m separation |
| gNB / UE counts E | 12 / 360, Table III p7 | 2 / 1, S:605–608 | Mismatch | D1 2/3, D2 3/5, staged resource-budgeted D3 |
| Bands E | Mixed FR1/FR2 ratio 0.7/0.3, Table III p7 | 3.5 GHz, 20 MHz, one BWP, S:659–660 | Mismatch | Exact FR1/FR2 carriers and bandwidths U; ratio alone does not specify an integer assignment for 12 sites |
| Mobility E | Bounded stochastic waypoint, speed [1,20] m/s, Table III p7 | ConstantVelocity, 5 m/s on +x; start (20,20,1.5), S:553–565,628–642 | Partial speed range; model mismatch | Record waypoint/pause/distribution and boundary rules; these are U in paper |
| Duration / step E | 300 s / 30 ms, Table III p7 | Default 30 s, validated B3 45 s; mobility step 30 ms | Partial | Matching mobility interval is not matching a synchronized graph time step |
| Heights/separation U | Not numerically specified in Table III / §V-A | gNBs (0,0,25), (300,0,25); UE height1.5 m | Unknown | Retain as project assumptions; cannot claim paper values |
| PHY/channel U | Exact propagation, fading, shadowing, antennas, scheduler, numerology, powers not specified in Table III / §V-A | UMa, ThreeGpp/Default helper arguments, ideal DirectPath beamforming; numerology1; gNB43 dBm, S:645–668; installed nr-helper.h:1009 | Unknown | Archive installed defaults/version; paper does not establish equivalence |
| Traffic E | Full-buffer UDP with periodic flow monitoring, Table III / §V-A1 | 512 bytes every10 ms =0.4096 Mbit/s offered UDP payload; 1 to T−1 s; 1 s drain; S:738–757 | Mismatch | Current traffic is low fixed-rate, not full-buffer; saturation study is a separate controlled change |
| Export E | UE–gNB pair jobs; all user-specific runs reuse site realization, §V-A1 p6 | One jointly simulated UE on actual serving cell; neighbour PHY reports | Mismatch | Serving-cell SINR is not an unexecuted target's post-handover QoS label |
| Handover architecture E | NG inter-gNB, AMF preparation, no usable Xn, §III-A p4 / §IV-A p5 / §V-A3 p7 | EPC + real RRC + X2; no AMF/NGAP/OAI, S:645,654,703–718 | Mismatch | Reproduction needs distinct replay and signalling stages; do not relabel X2 as NG |
| Base policies E | RSRP-A3, throughput-A3, SBGH, offline Q-learning/TD3/PPO, §V-A2 p6 / §V-C p8 | Only native A3-RSRP enabled in B3; Hys1.5 dB, TTT128 ms, S:653–657 | Partial | Paper's exact base-policy hysteresis/TTT and RL settings U; do not assume same algorithm tuning |
| Radio reporting U | Table III gives30 ms experiment interval, not exact PHY filters | RSRP/RSRQ ReportUeMeasurements default200 ms; event-driven DATA/CONTROL SINR | Unknown | Preserve source semantics; resampling at30 ms must expose age/missingness, not invent observations |
| Seed/run/count U | Replication count, seeds, confidence intervals not specified in requested evaluation sections | Recorded seed1/run1, S:551–552 | Unknown | Multi-seed independent runs and uncertainty are P, not paper facts |

## Digital Twin, risk and training

All entries below are absent from current implementation unless noted. They are requirements to investigate, not implemented parameters.

| Item / classification | Paper value and source | Current / match | Action and implication |
|---|---|---|---|
| PT / DT E | Directed PT includes UE/gNB/AMF/SMF/UPF; DT graph and services, definitions IV.1–3 / Eqs4–6, p5 | No graph model / mismatch | Separate physical entity registry from Table II UE/gNB feature matrix |
| Matrix E | 13 node columns, Table II p5 | Raw CSVs only / partial ingredients | Complete mapping and ambiguities in DT_FEATURE_SCHEMA.md |
| Model E | GCN encoder, VAE latent sampling, sigmoid inner-product adjacency decoder, GRU+MLP features; Eqs7–9 p5 | Not implemented | Layer widths, latent dimension, history L, rollout H, epsilon U; author clarification needed |
| Execution delay E/D | delta_hat=5 steps=150 ms, Table III p7; 5×30 ms=150 ms D | Native events only / mismatch | This is model input, not current measured standardized HIT |
| Monte Carlo E | M=10, Table III p7 / Algorithm1 p6 | None | Ten stochastic trajectories per candidate; no performance estimate here |
| Risk weights E | lambda_f=.65, lambda_q=.35, Table III / Eq10 | None | J=.65 Jfail+.35 Jqos |
| Failure E | gamma_RSRP=−110 dBm; gamma_RSRQ=−14 dB, Table III / Eq12 | No DT thresholds | Do not confuse thresholds with A3 hysteresis or SINR threshold |
| Geometry E/U | Escape margin delta(x)=dist(x,U-complement), U=source∪target coverage; Eqs1–3 p4; r=vmax delta_hat/(delta(x)+epsilon), Eq11 p6 | Positions/speed available; coverage boundary/Pmin/K/alpha not parameterized | Simple power-law disk model is conceptual, not validated UMa equivalence; epsilon value U |
| Acceptance E | Reject if Monte Carlo mean J > eta=.45; equality proceeds, Algorithm1 p6 / Table III | None | Explicit NGAP rejection proposed by paper, not supported here |
| QoS limits E | Ttarget20 Mbps; dmax150 ms; jmax50 ms; lmax.10; weights (.30,.20,.20,.30), Table III p7 / Eq13 p6 | No predictive risk; existing goodput/delay only | Loss scale needs explicit percent-to-fraction conversion; throughput layer/jitter estimator U |
| QoS equation D/U | Mean over H+1 predicted steps: wd*d/dmax+wj*j/jmax+wl*l/lmax+wt*(1−T/Ttarget), Eq13 p6 | None | No clipping specified; T>Ttarget makes throughput term negative. Do not silently clamp or assume score [0,1] |
| Data split E/U | 70/15/15%, §V-B p7 | No ML dataset | Unit of split / leakage controls U; propose realization/trajectory-grouped split |
| Training E | Adam lr.001, batch32,100 epochs, best validation-loss checkpoint; feature+adjacency+variational loss, §V-B p7 | None | Exact coefficients, normalization, architecture, random seeds, hardware U |
| Benchmarks E | LSTM,GRU,T-GCN,STGCN,STTGCN,STSGCN,DT-WIG, §V-B p7 | None | Results do not establish architecture-equivalent comparison |

Eq12 is the maximum over the post-execution horizon of an indicator for predicted RSRP below threshold OR predicted RSRQ below threshold OR geometric r>=1. Algorithm1 averages risks across M trajectories. Algorithm2 fixes the supplied adjacency during each rollout; Eq8 describes adjacency reconstruction. How reconstructed adjacency participates beyond training versus fixed rollout is U. Algorithm3 rewires both UE–source directions to0 and both UE–target directions to1, despite the general directed graph definition.

## Evaluation evidence; do not merge incompatible figures/tables

Table IV, p8 (training/testing seconds; marginal/full generative milliseconds):

| Model | Train s | Test s | Marginal ms | Full ms |
|---|---:|---:|---:|---:|
| LSTM |29.35|.60|.55|1.05|
| GRU |66.55|.65|.75|4.20|
| T-GCN |17.10|.60|.75|2.20|
| STGCN |25.65|.95|.55|1.70|
| STTGCN |68.25|.75|.70|4.45|
| STSGCN |151.00|1.30|.80|8.15|
| DT-WIG |118.75|.98|1.44|4.36|

No timing hardware, warm-up, dataset count, variance, batch normalization or precise marginal/full boundary is specified there. These are paper results, not project measurements. MAE/RMSE and adjacency AUC/AP are evaluated in §V-B and Figures4/5 p7; Table IV itself contains runtimes, not accuracy scores.

Table V, p9, RSS ablation (reported results, not our observations):

| Variant | HFR % | HIT ms | Throughput Mbps | Latency ms | PLR % | Reject % |
|---|---:|---:|---:|---:|---:|---:|
| A0 RSS |15.2|121|18.4|41.8|3.1|0.0|
| A1 linear rule validator |11.9|103|21.0|36.4|2.6|9.8|
| A2 GRU |10.8|96|22.1|33.7|2.2|11.4|
| A3 GCN+GRU |9.4|88|23.6|31.1|1.9|12.0|
| A4 GCN+GRU+VAE, failure only |8.6|82|24.0|30.4|1.7|13.5|
| A5 full DT-WIG |7.8|79|24.8|29.1|1.5|13.8|

§V-D p9 explains A1 as execution-time signal-quality linear extrapolation, A2 learned temporal, A3 graph-temporal, A4 stochastic failure-only, A5 combined risk. A1 extrapolation window/threshold details are U. These are distinct from this project's phase names.

Figure6 p8 was visually inspected: six paired bar panels show HFR, HIT, throughput, average latency, average jitter and average PLR across RSS/QoS/DF/Q-learning/TD3/PPO. DT-assisted bars improve reported metrics across policies. There are no printed bar-value labels, uncertainty intervals or raw data. HFR axis shows fractions (approximately .02–.18), whereas Table V reports percentages; do not copy the plotted fraction as a percent. RSS bars are not numerically identical to Table V (e.g. plotted HFR baseline near .16 versus table15.2%). Do not invent exact values or reconcile different evaluations without source data. Figure6 does not define failure denominators, HIT endpoints, jitter estimator or throughput layer.

## Blocking ambiguities

1. Table II gNB columns2–6 repeat average attached-UE RSRP without explaining five slot meanings. Top-four neighbour ordering/absent-neighbour policy and mean power domain are U.
2. Algorithm3 p7 line6 copies gNB column13 (Table II packet loss) to UE column13 (serving cell load). This is a semantic inconsistency, not permission to call loss load. Line5 updates RSRQ under a load comment. Preserve discrepancy; any repair is P and must be named.
3. H, L, epsilon, coverage constants, load/PRB denominators, QoS aggregation windows, post-execution failure verification time and data split grouping are U.
4. Accurate counterfactual target QoS cannot be recovered by swapping a passive neighbour RSRP into serving-cell QoS. The paper explicitly generates UE–gNB-specific runs and then evaluates replay/signalling separately.
5. Current one-packet loss, .4095 Mbps application goodput and 1.864286 ms UE RRC interval cannot be compared as matched reproductions of the paper's PLR, throughput or HIT.

## Equation and algorithm completeness notes

§III-B p4 defines P_r,i=P_tx,i*K_i*||x−b_i||^(−alpha_i), K_i>0, alpha_i>2, minimum received power Pmin and disk radius R_i=(P_tx,i*K_i/Pmin)^(1/alpha_i). No numeric K_i, alpha_i or Pmin is supplied. Eq1 is escape margin; Eq2 bounds displacement by vmax*tau_h; Eq3 constructs an escaping straight trajectory. Theorem1 gives a sufficient continuity condition tau_h<delta(x_d)/vmax; Theorem2 establishes existence of an escape trajectory when greater, not that every trajectory fails. Equality/boundary regularity, zero speed and exact coverage estimation are not resolved implementation prescriptions. Epsilon in Eq11 prevents a zero margin denominator but has no stated numerical value; if delta_hat is given in steps it must be converted to seconds before multiplying m/s.

Eq4 defines candidate `(UE,source,target)`. Eq5 defines time-indexed adjacency/features. Eq6 fuses measurements and derived service outputs; exact fusion/imputation is not specified. Eq7 produces latent mean/std; Gaussian epsilon~N(0,I) supplies stochasticity, distinct from geometric denominator epsilon. Eq8 uses sigmoid(ZZ^T), a symmetric reconstruction even though PT is defined directed; edge-direction modelling needs clarification. Eq9 maps latent history through GRU and MLP. Algorithms1/2 require history buffer L, future horizon H and rollouts, but neither L nor H has a numeric setting in TableIII. Algorithm1's no-candidate branch returns0, which must not be interpreted as a validator rejection in a proposed reject-rate denominator. Lines15–19 specify `HANDOVER PREPARATION FAILURE {radioNetwork:ho-target-not-allowed}` or standard NG preparation; current EPC/X2 cannot be credited with implementing either branch.

Paper §V-A does not specify Matérn hard-core distance/intensity, bounded-waypoint pause/turn distribution, exact FR1/FR2 carrier assignments, UE-specific flow rates/sizes, transport delays, RLC modes, scheduler, PRB-load calculation, model dimensions, adjacency negative sampling or evaluation hardware. These remain U rather than values inferred from our ns-3 defaults.
