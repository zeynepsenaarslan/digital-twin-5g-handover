#!/usr/bin/env python3
"""Validate keyed D1 v2 CSVs and plot actual per-UE observations (GPL-2.0-only)."""
import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import statistics

from phase_c22_sinr import load_sinr


def read(path, columns):
    """Require a named schema subset; never write simulation input."""
    with path.open(newline='') as f:
        reader=csv.DictReader(f)
        if not set(columns)<=set(reader.fieldnames or []):raise ValueError(f'Missing columns: {path}')
        result=list(reader)
    if not result:raise ValueError(f'Empty data: {path}')
    return result


def ns(value):
    """Use exact integer simulator nanoseconds for joins and window boundaries."""
    t=Decimal(value)*10**9
    if not t.is_finite() or t<0 or t!=int(t):raise ValueError('Invalid time')
    return int(t)


def finite(value):
    x=float(value)
    if not math.isfinite(x):raise ValueError('Nonfinite value')
    return x


def identity(row, registry):
    """IMSI is global within a run; UE and flow indices must agree with registry."""
    key=row['ue_id']
    if key not in registry or row['imsi']!=registry[key]['imsi']:raise ValueError('Misattributed UE/IMSI')
    if 'flow_id' in row and row['flow_id']!=registry[key]['flow_id']:raise ValueError('Misattributed flow')
    return key


def packet_accounting(packets, registry, summary):
    """Join actual successful TX and RX by (flow,sequence); reject silent duplicates."""
    tx,rx={},{};previous={};received=defaultdict(list)
    for p in packets:
        u=identity(p,registry);t=ns(p['time_s']);sent=ns(p['tx_time_s'])
        if p['event'] not in ('TX','RX') or p['valid']!='1' or int(p['udp_bytes'])!=512:raise ValueError('Invalid packet event')
        stream=(u,p['event'])
        if t<previous.get(stream,-1):raise ValueError('Unordered packets')
        previous[stream]=t
        key=(u,int(p['sequence']))
        if key[1]<0 or sent>t:raise ValueError('Invalid sequence/delay')
        table=tx if p['event']=='TX' else rx
        if key in table:raise ValueError('Duplicate packet event')
        table[key]=p
        if p['event']=='TX' and sent!=t:raise ValueError('TX timestamp mismatch')
        if p['event']=='RX':received[u].append(p)
    for key,p in rx.items():
        if key not in tx or p['tx_time_s']!=tx[key]['tx_time_s']:raise ValueError('RX without matching successful TX')
    for u in registry:
        seq=sorted(k[1] for k in tx if k[0]==u)
        if seq!=list(range(len(seq))):raise ValueError('Noncontiguous successful-send sequence')
        s=summary[u];actual=(len(seq),len(received[u]),512*len(received[u]))
        if actual!=tuple(int(s[k]) for k in ('tx_packets','rx_packets','rx_bytes')):raise ValueError('Packet counter mismatch')
        if int(s['rx_unique'])!=actual[1] or int(s['lost_unique'])!=actual[0]-actual[1]:raise ValueError('Unique/loss accounting mismatch')
    return received


def handovers(events,registry):
    """Pair each UE-local attempt without confusing equal RNTIs across cells."""
    active={};completed={};gnb=set();previous={};intervals=defaultdict(list);attached=Counter()
    for e in events:
        u=identity(e,registry);t=ns(e['time_s']);a=int(e['attempt_id']);key=(u,a)
        if t<previous.get(u,-1):raise ValueError('Unordered handovers')
        previous[u]=t
        if e['event']=='ConnectionEstablished':
            attached[u]+=1
            if e['source_cell_id']!=registry[u]['initial_cell_id']:raise ValueError('Initial cell mismatch')
        elif e['event']=='UE_HandoverStart':
            if u in active or a<=0 or key in completed:raise ValueError('Overlapping/reused attempt')
            active[u]=e
        elif e['event'] in ('UE_HandoverEndOk','UE_HandoverEndError'):
            start=active.pop(u,None)
            if start is None or start['attempt_id']!=e['attempt_id'] or any(start[k]!=e[k] for k in ('source_cell_id','target_cell_id')):raise ValueError('Unpaired/misattributed handover')
            completed[key]=e
            intervals[u].append(dict(start_s=float(start['time_s']),end_s=float(e['time_s']),
                source=e['source_cell_id'],target=e['target_cell_id'],success=e['event']=='UE_HandoverEndOk'))
        elif e['event']=='gNB_HandoverEndOk':
            end=completed.get(key)
            if not end or end['event']!='UE_HandoverEndOk' or key in gnb or any(e[k]!=end[k] for k in ('source_cell_id','target_cell_id','rnti')):raise ValueError('Unpaired gNB completion')
            gnb.add(key)
        else:raise ValueError('Unknown handover event')
    if active or any(attached[u]!=1 for u in registry):raise ValueError('Incomplete attempt/attachment')
    if any(e['event']=='UE_HandoverEndError' or k not in gnb for k,e in completed.items()):raise ValueError('Failed/incomplete D1 handover')
    return intervals


def validate(run):
    """Check actual producer, identities, physical streams and IP/application totals."""
    files=list(run.glob('*.csv'));hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    regs=read(run/'ue_registry_v2.csv',['ue_id','imsi','ipv4','flow_id','destination_port','initial_cell_id','vx_mps'])
    registry={r['ue_id']:r for r in regs}
    config=read(run/'run_config_v2.csv',['scenario','duration_s','sampling_ms','enable_handover'])[0]
    duration=finite(config['duration_s']);step=int(config['sampling_ms'])*1_000_000
    if config['scenario']!='d1' or duration<=2 or step<=0:raise ValueError('Invalid run configuration')
    if set(registry)!={'0','1','2'} or len(regs)!=3:raise ValueError('Expected three unique UEs')
    for key in ('imsi','ipv4','flow_id','destination_port'):
        if len({r[key] for r in regs})!=3:raise ValueError('Nonunique '+key)
    summaryRows=read(run/'udp_summary_v2.csv',['ue_id','imsi','tx_packets','rx_packets','rx_unique','rx_bytes','lost_unique'])
    summary={identity(s,registry):s for s in summaryRows}
    if len(summaryRows)!=3 or set(summary)!=set(registry):raise ValueError('Incomplete summary')
    packets=read(run/'udp_packets_v2.csv',['time_s','ue_id','imsi','flow_id','event','sequence','tx_time_s','udp_bytes','valid','cell_id','rnti'])
    received=packet_accounting(packets,registry,summary)
    for packet in packets:
        t=ns(packet['time_s']);sent=ns(packet['tx_time_s'])
        if t>int(duration*1e9) or not 1_000_000_000<=sent<int((duration-1)*1e9):raise ValueError('Packet outside declared observation/traffic interval')
        if sent!=1_000_000_000+int(packet['sequence'])*10_000_000:raise ValueError('TX grid violates recorded D1 traffic contract')
    events=read(run/'handover_events_v2.csv',['time_s','ue_id','imsi','attempt_id','event','source_cell_id','target_cell_id','rnti'])
    intervals=handovers(events,registry)
    mobility=read(run/'ue_mobility_v2.csv',['time_s','ue_id','imsi','x_m','y_m','z_m','vx_mps','vy_mps','vz_mps','speed_mps','valid'])
    byue=defaultdict(list)
    for m in mobility:
        u=identity(m,registry);byue[u].append(m);r=registry[u];t=ns(m['time_s'])/1e9
        for axis in 'xyz':
            v=finite(r['v'+axis+'_mps'])
            if not math.isclose(finite(m[axis+'_m']),finite(r[axis+'0_m'])+t*v,abs_tol=1e-7):raise ValueError('Mobility trajectory regression')
            if finite(m['v'+axis+'_mps'])!=v:raise ValueError('Velocity changed')
        speed=math.sqrt(sum(finite(r['v'+a+'_mps'])**2 for a in 'xyz'))
        if m['valid']!='1' or not math.isclose(finite(m['speed_mps']),speed,abs_tol=1e-7):raise ValueError('Mobility validity/speed')
    times=[ns(m['time_s']) for m in byue['0']]
    if times!=list(range(0,int(duration*1e9)+1,step)):raise ValueError('Invalid inclusive mobility grid')
    if any([ns(m['time_s']) for m in byue[u]]!=times for u in registry):raise ValueError('Incomplete UE mobility')
    expected_tx=math.ceil((duration-2)*100)
    for s in summary.values():
        if int(s['tx_packets'])!=expected_tx or int(s['rx_packets'])<=0 or s['active_attempt']!='0' or int(s['ho_errors']):raise ValueError('Invalid D1 final state')
    fm=read(run/'flow_monitor_v2.csv',['ue_id','source_ip','destination_ip','destination_port','protocol','tx_packets','rx_packets','tx_ip_bytes','rx_ip_bytes','lost_packets','unresolved_packets'])
    if len(fm)!=3 or {f['ue_id'] for f in fm}!=set(registry):raise ValueError('Missing/duplicate FlowMonitor mapping')
    for f in fm:
        u=f['ue_id'];r=registry[u];s=summary[u]
        if f['destination_ip']!=r['ipv4'] or f['destination_port']!=r['destination_port'] or f['protocol']!='17':raise ValueError('FlowMonitor attribution')
        for k in ('tx_packets','rx_packets'):
            if f[k]!=s[k]:raise ValueError('IP/application count mismatch')
        if int(f['tx_ip_bytes'])!=540*int(f['tx_packets']) or int(f['rx_ip_bytes'])!=540*int(f['rx_packets']):raise ValueError('D1 unfragmented IPv4/UDP byte mismatch')
        if int(f['tx_packets'])-int(f['rx_packets'])!=int(f['lost_packets'])+int(f['unresolved_packets']):raise ValueError('FlowMonitor outstanding/loss mismatch')
    radio=read(run/'radio_measurements.csv',['time_s','ue_id','imsi','metric','value','unit','source','serving_cell_id','measured_cell_id','is_serving','bwp_id'])
    previous={};seen=set();counts=Counter()
    for r in radio:
        u=identity(r,registry);t=ns(r['time_s']);finite(r['value'])
        if t>int(duration*1e9):raise ValueError('Radio outside observation')
        if r['metric'] not in ('rsrp','rsrq_model_derived') or r['unit']!=('dBm' if r['metric']=='rsrp' else 'dB') or r['source']!='NrUePhy::ReportUeMeasurements':raise ValueError('Radio units/source')
        if r['is_serving'] not in ('0','1') or (r['is_serving']=='1')!=(r['serving_cell_id']==r['measured_cell_id']):raise ValueError('Radio serving attribution')
        if r['measured_cell_id'] not in ('1','2') or r['bwp_id']!='0':raise ValueError('Unexpected D1 radio cell/BWP')
        key=(u,r['metric'],r['measured_cell_id'],r['bwp_id'])
        if t<previous.get(key,-1):raise ValueError('Unordered radio')
        previous[key]=t
        signature=tuple(r.items())
        if signature in seen:raise ValueError('Duplicate radio callback')
        seen.add(signature);counts[(u,r['metric'])]+=1
    sinr=load_sinr(run/'sinr_measurements.csv');scount=Counter();seen=set()
    for r in sinr:
        u=identity(r,registry);key=tuple((k,str(v)) for k,v in r.items())
        if r['ns']>int(duration*1e9):raise ValueError('SINR outside observation')
        if key in seen:raise ValueError('Duplicate SINR callback')
        seen.add(key);scount[(u,r['channel_type'])]+=1
        if r['cell_id'] not in ('1','2') or r['bwp_id']!='0':raise ValueError('Unknown SINR cell/BWP')
    serving=read(run/'serving_cells_v2.csv',['time_s','ue_id','imsi','cell_id','rnti','rrc_state','connected'])
    shistory=defaultdict(list)
    for r in serving:shistory[identity(r,registry)].append(r)
    for u in registry:
        if [ns(r['time_s']) for r in shistory[u]]!=times:raise ValueError('Incomplete serving history')
        if shistory[u][-1]['connected']!='1' or shistory[u][-1]['cell_id']!=summary[u]['final_cell_id']:raise ValueError('Final serving mismatch')
        hs=intervals[u]
        if int(summary[u]['ho_starts'])!=len(hs) or int(summary[u]['ho_ends'])!=len(hs) or int(summary[u]['gnb_ends'])!=len(hs):raise ValueError('Handover count mismatch')
        for channel in ('DL_DATA','DL_CONTROL'):
            if scount[(u,channel)]==0:raise ValueError('Missing SINR stream')
        for metric in ('rsrp','rsrq_model_derived'):
            if counts[(u,metric)]==0:raise ValueError('Missing radio stream')
        # Check each recorded completed target persists until the next start.
        for i,h in enumerate(hs):
            limit=hs[i+1]['start_s'] if i+1<len(hs) else duration
            post=[r for r in sinr if r['ue_id']==u and h['end_s']<r['t']<limit]
            if not post or any(r['cell_id']!=h['target'] for r in post):raise ValueError('SINR target attribution after handover')
            for channel in ('DL_DATA','DL_CONTROL'):
                if not any(r['channel_type']==channel for r in post):raise ValueError('No post-HO SINR channel')
    reports=read(run/'rrc_measurements_v2.csv',['time_s','ue_id','imsi','serving_cell_id','neighbour_cell_id','serving_rsrp_ie','neighbour_rsrp_ie']) if any(intervals.values()) else []
    for report in reports:
        identity(report,registry);ns(report['time_s'])
        if not all(0<=int(report[k])<=97 for k in ('serving_rsrp_ie','neighbour_rsrp_ie')):raise ValueError('Invalid quantized RRC RSRP')
    for u,hs in intervals.items():
        previous_end=0.0
        for h in hs:
            matching=[r for r in reports if r['ue_id']==u and r['serving_cell_id']==h['source'] and r['neighbour_cell_id']==h['target'] and previous_end<=float(r['time_s'])<=h['start_s']]
            if not matching:raise ValueError('Handover lacks matching actual preceding RRC A3 report')
            h['rrc_report_time_s']=max(float(r['time_s']) for r in matching)
            h['rrc_report_to_ue_start_ms']=1000*(h['start_s']-h['rrc_report_time_s'])
            previous_end=h['end_s']
    if len({f['source_ip'] for f in fm})!=1:raise ValueError('Unexpected traffic sources')
    for u,rows in shistory.items():
        for row in rows:
            t=finite(row['time_s'])
            if t<0 or t>duration or row['connected'] not in ('0','1'):raise ValueError('Invalid serving observation')
            hs=intervals[u]
            expected=registry[u]['initial_cell_id']
            in_attempt=False
            for h in hs:
                if h['start_s']<=t<=h['end_s']:in_attempt=True
                if t>h['end_s']:expected=h['target']
            if not in_attempt and row['connected']=='1' and row['cell_id']!=expected:raise ValueError('Serving history/event mismatch')
    result={'status':'PASS','duration_s':duration,'mobility_per_ue':len(times),'radio_rows':len(radio),'sinr_rows':len(sinr),'sinr_invalid_rows':sum(r['db'] is None for r in sinr),'input_sha256':hashes,'ues':{}}
    for u,r in registry.items():
        ps=received[u];delays=[(ns(p['time_s'])-ns(p['tx_time_s']))/1e6 for p in ps]
        s=summary[u];tx=int(s['tx_packets']);rx=int(s['rx_packets']);lost=tx-rx
        result['ues'][u]={'imsi':r['imsi'],'ipv4':r['ipv4'],'tx':tx,'rx':rx,'rx_bytes':int(s['rx_bytes']),'lost':lost,'pdr':rx/tx,
            'missing_sequences':sorted(set(range(tx))-{int(p['sequence']) for p in ps}),
            'mean_delay_ms':statistics.fmean(delays),'mean_abs_delay_variation_ms':statistics.fmean(abs(b-a) for a,b in zip(delays,delays[1:])) if len(delays)>1 else None,
            'observation_goodput_mbps':8*int(s['rx_bytes'])/(duration*1e6),'active_goodput_mbps':8*int(s['rx_bytes'])/((duration-2)*1e6),
            'final_cell':s['final_cell_id'],'handovers':intervals[u],
            'sinr':{c:scount[(u,c)] for c in ('DL_DATA','DL_CONTROL')},'flow_monitor':next(f for f in fm if f['ue_id']==u),'radio':{m:counts[(u,m)] for m in ('rsrp','rsrq_model_derived')}}
    result['aggregate']={k:sum(s[k] for s in result['ues'].values()) for k in ('tx','rx','rx_bytes','lost')}
    return result,dict(registry=registry,packets=received,mobility=byue,radio=radio,sinr=sinr,events=intervals,serving=shistory)


def plots(data,out,duration):
    """Scatter actual samples; no interpolation of PHY observations or lost packets."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':9,'svg.fonttype':'none'})
    names=[]
    def save(fig,name):
        fig.tight_layout()
        for ext in ('png','svg'):fig.savefig(out/(name+'.'+ext),dpi=300)
        plt.close(fig);names.append(name)
    def markers(ax,u):
        for h in data['events'][u]:
            ax.axvline(h['start_s'],color='crimson',ls='--',lw=.7)
            ax.axvline(h['end_s'],color='black',ls=':',lw=.7)
    fig,ax=plt.subplots(figsize=(8,4))
    for u,ms in data['mobility'].items():
        ax.plot([float(m['x_m']) for m in ms],[float(m['y_m']) for m in ms],label='UE '+u)
        ax.scatter(float(ms[0]['x_m']),float(ms[0]['y_m']),s=35)
    ax.scatter([0,300],[0,0],marker='^',s=70,label='gNB sites');ax.set(xlabel='x (m)',ylabel='y (m)',title='D1 deterministic trajectories (start marked)');ax.legend();save(fig,'d1_mobility')
    for kind in ('radio','sinr','qos','serving'):
        fig,axes=plt.subplots(3,2 if kind in ('qos','radio') else 1,figsize=(11,8),squeeze=False)
        for i,u in enumerate(sorted(data['registry'])):
            for ax in axes[i]:markers(ax,u);ax.set_xlabel('Simulation time (s)');ax.grid(alpha=.2)
            ax=axes[i,0];ax.set_title('UE '+u+' / IMSI '+data['registry'][u]['imsi'])
            if kind=='radio':
                for col,metric in enumerate(('rsrp','rsrq_model_derived')):
                    a=axes[i,col]
                    for cell in ('1','2'):
                        for role in ('0','1'):
                            rows=[r for r in data['radio'] if r['ue_id']==u and r['metric']==metric and r['measured_cell_id']==cell and r['is_serving']==role]
                            if rows:a.scatter([float(r['time_s']) for r in rows],[float(r['value']) for r in rows],s=6,marker='o' if role=='1' else 'x',color=f'C{int(cell)-1}',alpha=.7,label=f'cell {cell} '+('serving' if role=='1' else 'neighbour'))
                    a.set_ylabel('PHY RSRP (dBm)' if col==0 else 'Model-derived RSRQ (dB)');a.legend(fontsize=6)
            elif kind=='sinr':
                for channel in ('DL_DATA','DL_CONTROL'):
                    rows=[r for r in data['sinr'] if r['ue_id']==u and r['channel_type']==channel and r['db'] is not None]
                    ax.scatter([r['t'] for r in rows],[r['db'] for r in rows],s=2,label=channel,rasterized=True)
                ax.set_ylabel('Native SINR (dB)');ax.legend(fontsize=7)
            elif kind=='qos':
                ps=data['packets'][u];ts=[float(p['time_s']) for p in ps]
                ax.scatter(ts,[(ns(p['time_s'])-ns(p['tx_time_s']))/1e6 for p in ps],s=2);ax.set_ylabel('Received UDP delay (ms)')
                bins=[0]*math.ceil(duration*10)
                for p in ps:bins[min(ns(p['time_s'])//100_000_000,len(bins)-1)]+=int(p['udp_bytes'])
                axes[i,1].bar([j*.1 for j in range(len(bins))],[8*b/(min(.1,duration-j*.1)*1e6) for j,b in enumerate(bins)],width=.1,align='edge');axes[i,1].set_ylabel('UDP goodput (Mbit/s), 100 ms')
            else:
                rows=data['serving'][u];ax.step([float(r['time_s']) for r in rows],[int(r['cell_id']) for r in rows],where='post');ax.set_ylabel('Sampled RRC cell ID');ax.set_yticks([1,2])
        save(fig,'d1_'+kind)
    return names


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);args=p.parse_args()
    try:
        if args.output_dir.exists():raise ValueError('Choose fresh analysis directory')
        result,data=validate(args.run_dir)
        args.output_dir.mkdir(parents=True,exist_ok=False)
        # Persist per-received-packet QoS and complete 100 ms windows per UE.
        for name,header in [('qos_packets_v2.csv',['time_s','ue_id','imsi','sequence','delay_ms','abs_delay_variation_ms','delay_valid','variation_valid']),('qos_timeseries_v2.csv',['window_start_s','window_end_s','ue_id','imsi','rx_packets','rx_bytes','goodput_mbps','mean_delay_ms','delay_valid'])]:
            with (args.output_dir/name).open('x',newline='') as f:
                w=csv.writer(f);w.writerow(header)
                for u,r in data['registry'].items():
                    ps=data['packets'][u];previous=None
                    if name=='qos_packets_v2.csv':
                        for row in ps:
                            d=(ns(row['time_s'])-ns(row['tx_time_s']))/1e6
                            w.writerow([row['time_s'],u,r['imsi'],row['sequence'],d,'' if previous is None else abs(d-previous),1,int(previous is not None)]);previous=d
                    else:
                        for start in range(0,int(result['duration_s']*1e9),100_000_000):
                            end=min(start+100_000_000,int(result['duration_s']*1e9));group=[row for row in ps if start<=ns(row['time_s'])<end or (ns(row['time_s'])==end==int(result['duration_s']*1e9))];b=sum(int(x['udp_bytes']) for x in group)
                            delays=[(ns(x['time_s'])-ns(x['tx_time_s']))/1e6 for x in group]
                            w.writerow([start/1e9,end/1e9,u,r['imsi'],len(group),b,8*b/((end-start)*1e-9*1e6),statistics.fmean(delays) if delays else '',int(bool(delays))])
        result['plots']=plots(data,args.output_dir,result['duration_s'])
        for name,h in result['input_sha256'].items():
            if hashlib.sha256((args.run_dir/name).read_bytes()).hexdigest()!=h:raise ValueError('Input changed')
        (args.output_dir/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    except (ValueError,KeyError,OSError,ArithmeticError) as e:p.exit(1,f'FAIL: {e}\n')


if __name__=='__main__':main()
