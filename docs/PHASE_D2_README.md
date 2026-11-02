# D2: multi-gNB / multi-UE foundation and joining investigation

**D2 is not complete and no D2 release is declared.** The current scenario uses
three gNBs and five UEs. Native joining succeeds in the bounded recorded
23 dBm UE regression; the historical 2 dBm UE scenario still reproduces a
joining failure. Native failed-handover recovery remains a limitation.

The gNB transmit power is **43 dBm in both scenarios**. The changed quantity is
UE transmit power: inherited fixed **2 dBm** versus explicitly selected fixed
**23 dBm**, with uplink power control disabled. This is a scenario radio-budget
change, not a software root-cause fix in native RRC/PHY, a same-condition policy
improvement, or paper-parameter reproduction.

- [Joining evidence and native source/line references](D2_JOINING_ROOT_CAUSE.md)
- [Recorded joining campaign](PHASE_D2_JOINING_VALIDATION.json)
- [Preparation checks and native runner diagnosis](PHASE_D2_PREPARATION.md)
- [Current source hashes](PHASE_D2_SOURCE_MANIFEST.json)
- [Source synchronization provenance](PHASE_D2_SYNC_PROVENANCE.json)
- [Simulation Studio V1 plan](STUDIO_V1_PLAN.md)

## Historical evidence

[The 2026-10-30 foundation README](history/PHASE_D2_20261030_README.md) and
[its source manifest](history/PHASE_D2_20261030_SOURCE_MANIFEST.json) describe the
foundation snapshot introduced by commit b32387b. Their present-tense statements
and reproduction commands are historical; the executable default has since
changed. [PHASE_D2_VALIDATION.json](PHASE_D2_VALIDATION.json) is the unchanged
failed 2 dBm baseline. A reproducible failure must never be relabeled PASS just
because two executions are identical.

## Current reproduction

Use a separate compatible ns-3 3.48 / NR v5.0 checkout with examples and tests
enabled. Copy **all four** `simulation/dt-d2-*` files into its `scratch/` without
overwriting an existing research checkout. Build `dt-d2-simulation` there.
Check wrapper metadata agrees with the selected CMake build profile first.

From this repository root, with `NS3_ROOT` pointing to that external checkout,
use fresh output directories for every invocation:

```bash
python3 -B analysis/run_d2.py --ns3-root="$NS3_ROOT" --ue-tx-power=23 --seed=1 --output-dir=runs/d2-23-a
python3 -B analysis/run_d2.py --ns3-root="$NS3_ROOT" --ue-tx-power=23 --seed=1 --output-dir=runs/d2-23-b
python3 -B analysis/phase_d2.py --run-dir=runs/d2-23-a --compare-run=runs/d2-23-b --output-dir=runs/d2-23-report
D2_RUN_DIR=runs/d2-23-a python3 -B -m unittest discover -s analysis -p 'test_phase_*.py'
```

`run_d2.py` omits the UE CLI option when unspecified; the current C++ default
is 23 dBm. Explicitly pass it in published experiments. `radio_profile.json`
records the effective profile; each UE's effective attributes are checked.

To retain the historical reference, explicitly select 2 dBm:

```bash
python3 -B analysis/run_d2.py --ns3-root="$NS3_ROOT" --ue-tx-power=2 --diagnose-joining --output-dir=runs/d2-2-reference
python3 -B analysis/phase_d2.py --diagnostic --run-dir=runs/d2-2-reference --output-dir=runs/d2-2-diagnostic
python3 -B analysis/phase_d2_joining.py --run-dir=runs/d2-2-reference --output=runs/d2-2-proof.json
```

The reference producer failure (return code 1) and diagnostic blocked result
(return code 2) are expected evidence. Run commands separately so a failure
does not silently suppress analysis. `--joining-power-probe` is an opt-in
causal experiment, not a normal validated production run.

## Data contract and limits

`analysis/d2_schemas.json` defines the exact 19 raw CSV headers. The analyzer
produces six derived CSVs: candidates, per-packet QoS, unattributed packets,
cell PRB allocation, cell QoS, and UE-reported cell population. Effective radio
settings, execution manifests, source/binary/library hashes, schema/identity
checks and same-seed comparisons must remain attached to result interpretation.
Raw datasets and binaries are external local artifacts, not bundled here.

PRB allocation includes UL/DL DATA and MSG3, not queue demand or per-UE PRBs.
The initial bootstrap slot is absent; the first utilization window is invalid,
not zero-filled. Cell QoS is an S1-U ingress-cell end-to-end cohort; it does not
prove the last radio cell. Received-only delay excludes undelivered packets;
end-of-run undelivered/unresolved packets are not proven permanent drops.
RSRQ is model-derived. DATA and CONTROL SINR are distinct observations.

`serving_cells_v3.csv` reports UE RRC state. `gnb_context_v3.csv` only provides
a final target-context snapshot, not full-time gNB admission history. UE EndOk
does not prove gNB EndOk. Failure events remain visible and pending attempts
must not be synthesized as successful completions.

Remaining D2 work includes context membership over time, explicit failed-HO
recovery scope, declared ping-pong/recovery metrics and broader validation.
A3/A2A4 comparison is deferred. The next product priority is the separate,
read-only Studio V1 branch, not D3 scaling or a simulator-engine change.
