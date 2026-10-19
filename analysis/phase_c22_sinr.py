#!/usr/bin/env python3
"""Read, validate and plot actual native DL PHY SINR events (no interpolation)."""

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import json
import math
from pathlib import Path
import sys


SOURCES = {'DL_DATA':'NrUePhy::DlDataSinr', 'DL_CONTROL':'NrUePhy::DlCtrlSinr'}
SCHEMA = ['time_ns','time_s','ue_id','imsi','rnti','cell_id','bwp_id',
          'channel_type','sinr_linear','sinr_db','valid','status','source']


def validity(linear):
    """Mirror the producer's safe conversion policy, without inventing a value."""
    if not math.isfinite(linear): return 'nonfinite'
    if linear <= 0: return 'not_positive'
    if linear == sys.float_info.max: return 'empty_spectrum_sentinel'
    return 'ok'


def load_sinr(path):
    """Keep invalid original observations, but never give them a derived dB value."""
    with Path(path).open(newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != SCHEMA: raise ValueError('Unexpected SINR CSV schema')
        rows = list(reader)
    if not rows: raise ValueError('Empty SINR dataset')
    previous = {}
    for row in rows:
        time = int(row['time_ns'])
        if time < 0 or Decimal(row['time_s'])*1_000_000_000 != time:
            raise ValueError('Invalid SINR timestamp/unit')
        channel = row['channel_type']
        if channel not in SOURCES or row['source'] != SOURCES[channel]:
            raise ValueError('Unknown channel or wrong SINR trace source')
        for key in ('ue_id','imsi','rnti','cell_id','bwp_id'):
            if int(row[key]) < 0: raise ValueError('Negative identity')
        linear = float(row['sinr_linear'])
        status = validity(linear)
        if row['status'] != status or row['valid'] != ('1' if status=='ok' else '0'):
            raise ValueError('SINR validity flag/status mismatch')
        db = None
        if status == 'ok':
            db = float(row['sinr_db'])
            if not math.isfinite(db) or not math.isclose(db,10*math.log10(linear),abs_tol=1e-10):
                raise ValueError('Incorrect linear-to-dB conversion')
        elif row['sinr_db'] != '':
            raise ValueError('Invalid SINR must have a missing dB value')
        key = tuple(row[k] for k in ('ue_id','imsi','bwp_id','channel_type'))
        if time < previous.get(key,-1): raise ValueError('Nonmonotonic SINR stream')
        previous[key] = time
        row.update(t=time/1e9, ns=time, db=db)
    return rows


def summarize(samples):
    """Report actual stream counts, ranges, identities and exact duplicate records."""
    groups = defaultdict(list)
    for s in samples: groups[s['channel_type']].append(s)
    result = {}
    for channel,rows in groups.items():
        valid = [r for r in rows if r['db'] is not None]
        signatures = [tuple(r[k] for k in SCHEMA) for r in rows]
        result[channel] = dict(samples=len(rows),valid=len(valid),invalid=len(rows)-len(valid),
            invalid_reasons=dict(Counter(r['status'] for r in rows if r['db'] is None)),
            first_time_s=rows[0]['t'],last_time_s=rows[-1]['t'],
            min_db=min((r['db'] for r in valid),default=None),
            max_db=max((r['db'] for r in valid),default=None),
            cell_counts=dict(Counter(r['cell_id'] for r in rows)),
            preconnection_rnti_zero=sum(r['rnti']=='0' for r in rows),
            exact_duplicate_rows=len(signatures)-len(set(signatures)))
    return result


def validate_run(run, reference):
    """Compare all six previous CSVs byte-for-byte, including passive RSRP/RSRQ."""
    samples = load_sinr(run/'sinr_measurements.csv')
    legacy = ['ue_mobility.csv','udp_packets.csv','udp_traffic.csv',
              'handover_events.csv','handover_measurements.csv','radio_measurements.csv']
    for name in legacy:
        if (run/name).read_bytes() != (reference/name).read_bytes():
            raise ValueError('Regression in '+name)
    with (run/'handover_events.csv').open() as f: events=list(csv.DictReader(f))
    starts = [r for r in events if r['event']=='UE_HandoverStart']
    ends = [r for r in events if r['event']=='UE_HandoverEndOk']
    if len(starts)!=1 or len(ends)!=1: raise ValueError('Expected one real UE handover')
    start,end = float(starts[0]['time_s']),float(ends[0]['time_s'])
    target = ends[0]['target_cell_id']
    summary = summarize(samples)
    for channel,stats in summary.items():
        if stats['exact_duplicate_rows']: raise ValueError('Unexpected exact duplicate SINR rows')
        rows = [r for r in samples if r['channel_type']==channel]
        if not any(r['t']<start and r['cell_id']==starts[0]['source_cell_id'] for r in rows):
            raise ValueError('No source-cell SINR before handover')
        after = [r for r in rows if r['t']>end]
        if not after or any(r['cell_id']!=target for r in after):
            raise ValueError('Missing or misattributed post-handover SINR')
        stats['samples_after_ue_completion']=len(after)
    return dict(status='PASS',legacy_csv_byte_identity='PASS (six files)',
                channels=summary,total_samples=len(samples),
                handover_start_s=start,handover_end_s=end,
                data_trace_emitted='VERIFIED' if 'DL_DATA' in summary else 'NOT OBSERVED',
                control_trace_emitted='VERIFIED' if 'DL_CONTROL' in summary else 'NOT OBSERVED',
                caveat='A3 uses RSRP; SINR does not cause the recorded handover')


def render_sinr(samples, output, events, zoom_seconds, mark_events):
    """Add two scatter figures; all valid samples are used, invalid dB stays missing."""
    import matplotlib.pyplot as plt
    starts = [float(e['time_s']) for e in events if e['event']=='UE_HandoverStart']
    ends = [float(e['time_s']) for e in events if e['event']=='UE_HandoverEndOk']
    bounds = (max(0,starts[0]-zoom_seconds),ends[0]+zoom_seconds) if starts and ends else None
    figures = {}
    for name,limits in [('sinr_full',None),('sinr_handover',bounds)]:
        fig,ax = plt.subplots(figsize=(10,5),layout='constrained')
        counts = {}
        for i,channel in enumerate(SOURCES):
            rows = [s for s in samples if s['channel_type']==channel and s['db'] is not None
                    and (limits is None or limits[0]<=s['t']<=limits[1])]
            if not rows: continue
            # Preserve every actual point; rasterize dense point layers only in SVG.
            ax.scatter([r['t'] for r in rows],[r['db'] for r in rows],s=3 if not limits else 8,
                       marker='o' if i==0 else 'x',alpha=.65,color=f'C{i}',label=channel,
                       rasterized=len(rows)>2000)
            counts[channel]=len(rows)
        if not counts:
            plt.close(fig)
            raise ValueError('No valid SINR samples in requested plotting range')
        mark_events(ax,events)
        ax.set(xlabel='Simulation time (s)',ylabel='DL SINR (dB)',
               title='Native DL DATA / CONTROL SINR'+(' around handover' if limits else ''))
        if limits: ax.set_xlim(*limits)
        ax.grid(True,alpha=.22);ax.legend(loc='best')
        for extension in ('png','svg'):
            path=output/f'{name}.{extension}'
            if path.exists(): raise ValueError('SINR plot already exists')
            fig.savefig(path,dpi=300)
        plt.close(fig);figures[name]=counts
    return figures


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--reference-dir',type=Path,required=True)
    args=p.parse_args()
    try: print(json.dumps(validate_run(args.run_dir,args.reference_dir),indent=2,allow_nan=False))
    except (ValueError,OSError,KeyError,ArithmeticError) as error:p.exit(1,f'FAIL: {error}\n')


if __name__=='__main__': main()
