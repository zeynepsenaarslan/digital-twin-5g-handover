#!/usr/bin/env python3
"""Correlate the recorded D2 UE1 attempt6 native evidence; GPL-2.0-only."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def fields(detail):
    """Decode scalar diagnostic details without inventing missing values."""
    return dict(item.split('=',1) for item in detail.split(';') if '=' in item)


def summarize(rows):
    """Prove context order and distinguish noise-limited TB loss from missing context."""
    times=[int(r['time_ns']) for r in rows]
    if times!=sorted(times) or [int(r['sequence']) for r in rows]!=list(range(len(rows))):
        raise ValueError('Diagnostic event order invalid')
    target=[r for r in rows if r['cell_id']=='2' and r['rnti']=='5']
    events={name:[r for r in target if r['event']==name] for name in
            ('CONTEXT_CREATED','AFTER_CREATE','JOIN_TIMEOUT_FIRED','RELEASE_BEFORE_ERASE','AFTER_ERASE')}
    if any(len(v)!=1 for v in events.values()):raise ValueError('Missing/duplicate context lifecycle evidence')
    lifecycle=[events[name][0] for name in events]
    if [int(r['sequence']) for r in lifecycle]!=sorted(int(r['sequence']) for r in lifecycle):
        raise ValueError('Context lifecycle order invalid')
    created,identified,failure,releasing,erased=lifecycle
    if fields(identified['detail'])!={'present':'1','state':'8'} or identified['imsi']!='4':
        raise ValueError('Target context was not identified as HANDOVER_JOINING')
    if fields(failure['detail'])!={'present':'1','state':'8'} or fields(releasing['detail'])!={'present':'1','state':'8'} or fields(erased['detail'])!={'present':'0'}:
        raise ValueError('Context presence at timeout/erase contradicts claimed cause')
    if int(failure['time_ns'])-int(created['time_ns'])!=200_000_000:
        raise ValueError('Joining watchdog duration differs from unchanged native 200 ms')
    if len({r['time_ns'] for r in (failure,releasing,erased)})!=1:
        raise ValueError('Timeout and removal not in same native event time')
    start=int(created['time_ns']);end=int(failure['time_ns'])
    episode=[r for r in target if start<=int(r['time_ns'])<=end]
    raw=[r for r in episode if r['event']=='UL_TB']
    # Native RxPacketTraceGnb emits once per packet in a TB, not once per TB.
    tb=list({(r['time_ns'],r['detail']):r for r in raw}.values())
    snr={r['time_ns']:float(fields(r['detail'])['linear']) for r in rows if r['event']=='SNR' and r['cell_id']=='2'}
    if not tb or any(r['time_ns'] not in snr for r in tb):raise ValueError('Missing native SNR/TB pairing')
    sinr=[float(fields(r['detail'])['sinr']) for r in tb]
    max_delta=max(abs(snr[r['time_ns']]-float(fields(r['detail'])['sinr'])) for r in tb)
    if any(fields(r['detail'])['rb']!='53' for r in tb):raise ValueError('Full-band SNR requires matching all 53 RBs')
    ul=[r for r in episode if r['event']=='UL_TX']
    powers=sorted({float(fields(r['detail'])['dbm']) for r in ul})
    counts={layer:sum(r['layer']==layer and r['event']==event for r in episode)
            for layer,event in [('UE_PDCP','TX'),('UE_RLC','TX'),('gNB_RLC','RX'),('gNB_PDCP','RX')]}
    if not counts['UE_PDCP'] or not counts['UE_RLC'] or counts['gNB_RLC'] or counts['gNB_PDCP']:
        raise ValueError('SRB evidence contradicts uplink delivery failure')
    if powers!=[2.0] or max_delta>1e-6 or any(fields(r['detail'])['corrupt']!='1' for r in tb):
        raise ValueError('Noise-limited 2 dBm diagnosis not supported')
    return dict(status='ROOT_CAUSE_PROVEN_AT_PHY_DELIVERY_BOUNDARY',
                hypothesis_context_absent_before_timeout=False,
                hypothesis_interference_dominant=False,
                cause='Native SRB1 UL transport blocks are noise-limited at the inherited fixed 2 dBm profile; no RRC complete reaches target before watchdog.',
                target_context_created_ns=start,joining_timeout_ns=end,watchdog_ns=end-start,
                context_present_during_failure=True,context_erased_after_failure_same_timestamp=True,
                native_tb_trace_rows=len(raw),unique_transport_blocks=len(tb),corrupt_transport_blocks=len(tb),
                sinr_db_range=[10*math.log10(min(sinr)),10*math.log10(max(sinr))],
                max_abs_native_snr_minus_sinr=max_delta,actual_ul_power_dbm=powers,srb_counts=counts,
                context_lifecycle=lifecycle,
                last_success=[r for r in rows if (r['imsi']=='4' or r['layer']=='X2_IP') and int(r['time_ns'])<38_000_000_000 and r['layer'] in ('UE_RRC','gNB_RRC','X2_IP')],
                attempt6_chain=[r for r in rows if 49_540_000_000<=int(r['time_ns'])<=end and
                                (r['layer'] in ('UE_RRC','gNB_RRC','X2_IP','EXPERIMENT') or
                                 (r['cell_id']=='2' and r['rnti']=='5' and r['event'] in ('RA_SUCCESS','TX','RX')))])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();path=args.run_dir/'diagnostics/timeline.csv'
    with path.open(newline='') as stream:result=summarize(list(csv.DictReader(stream)))
    result['timeline_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with args.output.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({k:v for k,v in result.items() if not isinstance(v,list)},indent=2))


if __name__=='__main__':main()
