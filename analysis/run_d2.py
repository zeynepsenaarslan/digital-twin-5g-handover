#!/usr/bin/env python3
"""Run the isolated D2 executable with immutable provenance (GPL-2.0-only)."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time


def digest(path):
    """Hash a file in bounded memory."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def limits():
    """Bound a small D2 child to 1.5 GiB address space and ten CPU minutes."""
    resource.setrlimit(resource.RLIMIT_AS,(1536*1024**2,1536*1024**2))
    resource.setrlimit(resource.RLIMIT_CPU,(600,600))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ns3-root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--sim-time',type=float,default=90)
    parser.add_argument('--turn-time',type=float,default=40)
    parser.add_argument('--sampling-ms',type=int,default=30)
    parser.add_argument('--seed',type=int,default=1)
    parser.add_argument('--run',type=int,default=1)
    parser.add_argument('--ue-tx-power',type=float)
    parser.add_argument('--diagnose-joining',action='store_true')
    parser.add_argument('--joining-power-probe',action='store_true')
    args=parser.parse_args(); root=args.ns3_root.resolve();output=args.output_dir.resolve()
    if output.exists():parser.error('Output directory must be fresh')
    version=(root/'VERSION').read_text().strip()
    executable=root/'build/scratch'/('ns'+version+'-dt-d2-simulation')
    # VERSION is 3.48, executable prefix is ns3.48.
    if not executable.is_file():parser.error('Build dt-d2-simulation first')
    output.parent.mkdir(parents=True,exist_ok=True)
    sources=list((root/'scratch').glob('dt-d2-*'))
    libraries=list((root/'build/lib').glob('*.so'))
    files=sources+[executable]+libraries
    hashes={str(p.relative_to(root)):digest(p) for p in files if p.is_file()}
    command=[str(executable),f'--simTime={args.sim_time}',f'--turnTime={args.turn_time}',
             f'--samplingMs={args.sampling_ms}',f'--seed={args.seed}',f'--run={args.run}',f'--outputDir={output}']
    if args.ue_tx_power is not None:command.append(f'--ueTxPower={args.ue_tx_power}')
    if args.diagnose_joining:command.append('--diagnoseJoining=1')
    if args.joining_power_probe:command.append('--joiningPowerProbe=1')
    started=time.time();begin=time.monotonic()
    with output.with_suffix('.log').open('x') as log:
        child=subprocess.Popen(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,preexec_fn=limits)
        try:code=child.wait(timeout=660)
        except subprocess.TimeoutExpired:
            child.kill();child.wait();code=124
    unchanged=all(digest(root/p)==h for p,h in hashes.items())
    manifest=dict(command=command,started_unix_s=started,elapsed_s=time.monotonic()-begin,
                  max_rss_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                  returncode=code,ns3_version=version,source_binary_library_sha256=hashes,
                  files_unchanged_during_run=unchanged,
                  output_bytes=sum(p.stat().st_size for p in output.glob('*') if p.is_file()),
                  resource_limits=dict(address_space_mib=1536,cpu_seconds=600,wall_seconds=660),
                  rng_policy='NrHelper::AssignStreams(StreamAssignmentParams): EPC, remote/UE/gNB nodes, beamforming, gNB/UE devices; native base offsets')
    if output.is_dir():(output/'run_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k!='source_binary_library_sha256'},indent=2))
    raise SystemExit(0 if code==0 and unchanged else 1)


if __name__=='__main__':main()
