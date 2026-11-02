#!/usr/bin/env python3
"""Validate independent D2 evidence; GPL-2.0-only. No D1 files are written."""
import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
from phase_c22_sinr import load_sinr

SCHEMAS = json.loads(Path(__file__).with_name('d2_schemas.json').read_text())


def rows(run, name):
    """Stream an exact CSV schema, including empty optional event datasets."""
    with (run / name).open(newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != SCHEMAS[name]:
            raise ValueError('CSV schema mismatch: ' + name)
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError('Malformed CSV row: ' + name)
            yield row


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


def handovers(events,registry,require_gnb_completion=True):
    """Pair each UE-local attempt without confusing equal RNTIs across cells."""
    active={};completed={};gnb=set();previous={};intervals=defaultdict(list);attached=Counter()
    for e in events:
        u=identity(e,registry);t=ns(e['time_s']);a=int(e['attempt_id']);key=(u,a)
        if t<previous.get(u,-1):raise ValueError('Unordered handovers')
        previous[u]=t
        if e['event']!='ConnectionEstablished' and attached[u]!=1:raise ValueError('Handover before initial attachment')
        if e['event']=='ConnectionEstablished':
            if a!=0 or e['source_cell_id']!=e['target_cell_id']:raise ValueError('Invalid initial attachment event')
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
                source=e['source_cell_id'],target=e['target_cell_id'],success=e['event']=='UE_HandoverEndOk',
                attempt_id=int(start['attempt_id']),source_rnti=start['rnti'],target_rnti=e['rnti']))
        elif e['event']=='gNB_HandoverEndOk':
            end=completed.get(key)
            if not end or end['event']!='UE_HandoverEndOk' or key in gnb or any(e[k]!=end[k] for k in ('source_cell_id','target_cell_id','rnti')):raise ValueError('Unpaired gNB completion')
            gnb.add(key)
        else:raise ValueError('Unknown handover event')
    if active or any(attached[u]!=1 for u in registry):raise ValueError('Incomplete attempt/attachment')
    if any(e['event']=='UE_HandoverEndError' or (require_gnb_completion and k not in gnb) for k,e in completed.items()):raise ValueError('Failed/incomplete D2 handover')
    for u,hs in intervals.items():
        for h in hs:
            h['gnb_completed']=(u,h['attempt_id']) in gnb
            h['ue_end_ok']=h['success']
            h['success']=h['ue_end_ok'] and h['gnb_completed']
    return intervals


def unique_registry(records, key, count):
    """Reject duplicate or missing registry identities."""
    result = {r[key]: r for r in records}
    if len(result) != count or len(records) != count:
        raise ValueError('Registry cardinality/duplicates: ' + key)
    return result


def trajectory(reg, t, turn):
    """Analytic outbound, return and stopped position/velocity, right-continuous."""
    elapsed = t if t < turn else max(0, 2 * turn - t)
    sign = 1 if t < turn else -1 if t < 2 * turn else 0
    position = [finite(reg[a+'0_m']) + finite(reg['v'+a+'_mps'])*elapsed for a in 'xyz']
    velocity = [sign*finite(reg['v'+a+'_mps']) for a in 'xyz']
    return position, velocity


def candidate_rows(radio, registry, cells):
    """Rank same-epoch observed PHY neighbours; explicitly mask absent cells."""
    epochs = defaultdict(dict)
    for r in radio:
        identity(r, registry)
        if r['metric'] != 'rsrp':
            continue
        key = (r['time_s'], r['ue_id'], r['bwp_id'], r['serving_cell_id'])
        if r['measured_cell_id'] in epochs[key]:
            raise ValueError('Duplicate candidate measurement')
        epochs[key][r['measured_cell_id']] = finite(r['value'])
    result = []
    coverage = Counter()
    for (t, u, bwp, serving), powers in sorted(epochs.items()):
        neighbours = sorted((c for c in powers if c != serving), key=lambda c: (-powers[c], int(c)))
        if serving in powers and len(neighbours) == len(cells)-1:
            coverage[u] += 1
        for c in sorted(cells, key=int):
            if c == serving:
                continue
            measured = c in powers
            result.append(dict(time_s=t, ue_id=u, imsi=registry[u]['imsi'], bwp_id=bwp,
                               serving_cell_id=serving, candidate_cell_id=c, measured=int(measured),
                               rsrp_dbm=powers[c] if measured else '',
                               rank=neighbours.index(c)+1 if measured else '',
                               source='same_epoch_PHY_RSRP'))
    if any(coverage[u] == 0 for u in registry):
        raise ValueError('Missing simultaneous two-neighbour coverage')
    return result, dict(coverage)


def validate_slots(records, cells, duration_ns, allow_bootstrap_gap=False):
    """Validate native slots; explicitly mask the known unreported bootstrap slot."""
    expected = {c: 0 for c in cells}
    totals = {c: dict(slots=0, allocated_prb_symbols=0, available_prb_symbols=0, idle_slots=0, missing_slot_indices=[]) for c in cells}
    bins = defaultdict(lambda: [0, 0, 0])
    for r in records:
        c = r['cell_id']
        if c not in cells or r['bwp_id'] != cells[c]['bwp_id']:
            raise ValueError('Unknown PRB cell/BWP')
        t = ns(r['time_s']); slot = int(r['slot_index'])
        if allow_bootstrap_gap and expected[c]==1 and slot==2:
            totals[c]['missing_slot_indices'].append(1);expected[c]=2
        if slot != expected[c] or t != slot*500_000 or t > duration_ns:
            raise ValueError('PRB slot gap/duplicate/time')
        expected[c] += 1
        used, symbols, rb, available, full, active = [int(r[k]) for k in
            ('allocated_prb_symbols','data_symbols','available_prbs','available_symbols','full_slot_symbols','active_rntis')]
        if rb <= 0 or full != 14 or not 0 <= symbols <= available <= full or not 0 <= used <= rb*available or active < 0:
            raise ValueError('PRB denominator/overflow')
        if r['source'] != 'NrGnbPhy::SlotDataStats':
            raise ValueError('Not native PRB evidence')
        total = totals[c]; total['slots'] += 1; total['allocated_prb_symbols'] += used
        total['available_prb_symbols'] += rb*available; total['idle_slots'] += used == 0
        # Exclude the exact final boundary slot from [0,duration) window rates.
        if t < duration_ns:
            b = bins[(t//100_000_000, c)]; b[0] += used; b[1] += rb*available; b[2] += 1
    if any(n != duration_ns//500_000+1 for n in expected.values()):
        raise ValueError('Incomplete PRB slot coverage')
    if any(not t['idle_slots'] or not t['allocated_prb_symbols'] for t in totals.values()):
        raise ValueError('Missing idle/active PRB evidence')
    return totals, bins


def ingress_qos(ingress, packets, registry, cells, duration_ns, allow_unattributed=False):
    """Join actual ingress-cell cohorts to successful sends and application delivery."""
    tx = {}; rx = {}
    for p in packets:
        identity(p, registry)
        key = (p['ue_id'], p['sequence'])
        (tx if p['event']=='TX' else rx)[key] = p
    seen = {}; bins = defaultdict(list)
    totals = {c: dict(ingress_packets=0, rx_packets=0, rx_bytes=0, undelivered=0) for c in cells}
    delays = defaultdict(list)
    packet_rows = []
    for r in ingress:
        u = identity(r, registry); key = (u, r['sequence']); c = r['cell_id']; t = ns(r['time_s'])
        if c not in cells or key in seen or key not in tx:
            raise ValueError('Duplicate/unknown ingress cell or packet')
        sent = tx[key]
        if r['tx_time_s'] != sent['tx_time_s'] or r['udp_bytes'] != sent['udp_bytes'] or not ns(sent['time_s']) <= t <= duration_ns:
            raise ValueError('Ingress timestamp/payload mismatch')
        if r['source'] != 'NrEpcGnbApplication::RxFromS1u':
            raise ValueError('Not native S1-U ingress evidence')
        seen[key] = c; totals[c]['ingress_packets'] += 1
        if key in rx:
            p = rx[key]; received = ns(p['time_s'])
            if received < t:
                raise ValueError('RX before cell ingress')
            delay = (received-ns(sent['time_s']))/1e6
            totals[c]['rx_packets'] += 1; totals[c]['rx_bytes'] += int(p['udp_bytes']); delays[c].append(delay)
            bins[(min(received//100_000_000, (duration_ns-1)//100_000_000), c)].append((int(p['udp_bytes']),delay))
            packet_rows.append(dict(time_s=p['time_s'],ue_id=u,imsi=p['imsi'],flow_id=p['flow_id'],sequence=p['sequence'],
                                    ingress_cell_id=c,ingress_time_s=r['time_s'],rx_rrc_cell_id=p['cell_id'],
                                    udp_bytes=p['udp_bytes'],delay_ms=delay,attribution='S1U_ingress_cohort'))
        else:
            totals[c]['undelivered'] += 1
    missing=set(tx)-set(seen)
    if missing and not allow_unattributed:
        raise ValueError('TX lacks actual cell ingress; attribution incomplete')
    if missing & set(rx):raise ValueError('Received packet lacks ingress instrumentation')
    for c, total in totals.items():
        total['delivery_fraction'] = total['rx_packets']/total['ingress_packets'] if total['ingress_packets'] else None
        total['mean_received_delay_ms'] = statistics.fmean(delays[c]) if delays[c] else None
    if sum(t['rx_packets'] for t in totals.values()) != len(rx):
        raise ValueError('Cell QoS conservation failure')
    if missing:
        totals['_unattributed']=[dict(ue_id=u,imsi=registry[u]['imsi'],flow_id=registry[u]['flow_id'],sequence=seq,
                                     tx_time_s=tx[(u,seq)]['tx_time_s'],udp_bytes=tx[(u,seq)]['udp_bytes'],
                                     reason='no_observed_S1U_ingress') for u,seq in sorted(missing,key=lambda k:(int(k[0]),int(k[1])))]
    return totals, bins, packet_rows


def link_failures(failures, intervals):
    """Link joining/leaving failures only through native IMSI/cell/RNTI evidence."""
    for f in failures:
        if f['event'] not in ('HandoverFailureJoining','HandoverFailureLeaving'):
            f.update(attempt_id='',attempt_link_valid=0)
            continue
        joining=f['event']=='HandoverFailureJoining'
        cell_key='target' if joining else 'source'
        rnti_key='target_rnti' if joining else 'source_rnti'
        matches=[h for h in intervals[f['ue_id']] if h[cell_key]==f['cell_id'] and h[rnti_key]==f['rnti'] and h['start_s']<=float(f['time_s'])]
        if not matches:raise ValueError('Native failure lacks matching cell/RNTI attempt')
        matched=max(matches,key=lambda h:h['start_s'])
        f.update(attempt_id=matched['attempt_id'],attempt_link_valid=1)


def validate(run, allow_pending=False):
    """Check raw producer evidence without writing or repairing inputs."""
    if {p.name for p in run.glob('*.csv')} != set(SCHEMAS):
        raise ValueError('Unexpected/missing raw CSV files')
    hashes = {n: hashlib.sha256((run/n).read_bytes()).hexdigest() for n in SCHEMAS}
    configs = list(rows(run,'run_config_v3.csv'))
    if len(configs) != 1:
        raise ValueError('Expected one configuration')
    config = configs[0]; duration = finite(config['duration_s']); end = ns(config['duration_s']); turn = finite(config['turn_s'])
    step = int(config['sampling_ms'])*1_000_000
    if end%500_000 or end%step:raise ValueError('Duration must align with slot and sampling grids')
    if config['scenario'] != 'd2' or config['enable_handover'] != '1' or not 1 < turn < (duration-1)/2 or step <= 0:
        raise ValueError('Invalid D2 configuration')
    for k,v in dict(carrier_hz=3500000000, bandwidth_hz=20000000,hysteresis_db=1.5,ttt_ms=128,traffic_interval_ms=10,udp_bytes=512).items():
        if finite(config[k]) != v:
            raise ValueError('Changed baseline radio/traffic contract: '+k)
    if finite(config['stop_motion_s']) != 2*turn:
        raise ValueError('Invalid return stop time')
    registry = unique_registry(list(rows(run,'ue_registry_v3.csv')),'ue_id',5)
    cells = unique_registry(list(rows(run,'cell_registry_v3.csv')),'cell_id',3)
    if set(registry) != {str(i) for i in range(5)}:
        raise ValueError('Unexpected UE indices')
    for k in ('imsi','node_id','ipv4','flow_id','destination_port'):
        if len({r[k] for r in registry.values()}) != 5:
            raise ValueError('Nonunique UE registry '+k)
    for k in ('gnb_id','node_id'):
        if len({r[k] for r in cells.values()}) != 3:
            raise ValueError('Nonunique cell registry '+k)
    if any(r['initial_cell_id'] not in cells for r in registry.values()) or any(c['bwp_id'] != '0' for c in cells.values()):
        raise ValueError('Registry cell/BWP mismatch')
    # Freeze the published geometry and initial association by gNB index, not guessed cell IDs.
    sites = sorted(cells.values(),key=lambda c:int(c['gnb_id']))
    expected_sites = ((0,0,25),(300,0,25),(150,259.807621135,25))
    starts = ((20,20,1.5),(280,20,1.5),(150,239.807621135,1.5),(150,180,1.5),(25,60,1.5))
    velocities = ((5,0,0),(-2.5,4.330127019,0),(-2.5,-4.330127019,0),(0,0,0),(0,0,0))
    for cell, xyz in zip(sites,expected_sites):
        if any(not math.isclose(finite(cell[a+'_m']),v,abs_tol=1e-8) for a,v in zip('xyz',xyz)):
            raise ValueError('Changed D2 site geometry')
    for i,(xyz,vel) in enumerate(zip(starts,velocities)):
        reg = registry[str(i)]
        if reg['initial_cell_id'] != sites[i if i<3 else 2 if i==3 else 0]['cell_id']:
            raise ValueError('Changed initial attachment plan')
        if any(not math.isclose(finite(reg[a+'0_m']),p,abs_tol=1e-8) or not math.isclose(finite(reg['v'+a+'_mps']),v,abs_tol=1e-8) for a,p,v in zip('xyz',xyz,vel)):
            raise ValueError('Changed D2 motion plan')
    x2 = list(rows(run,'x2_registry_v3.csv'))
    pairs = {frozenset((r['source_cell_id'],r['target_cell_id'])) for r in x2}
    if len(x2)!=3 or pairs != {frozenset(p) for p in itertools.combinations(cells,2)}:
        raise ValueError('Incomplete/duplicate X2 registry')
    traces = list(rows(run,'trace_registry_v3.csv'))
    actual = {tuple(r.values()) for r in traces}; expected=set()
    for u,r in registry.items():
        for name in ('ConnectionEstablished','HandoverStart','HandoverEndOk','HandoverEndError'):
            expected.add(('UE',r['node_id'],u,r['imsi'],'','',name,'NrUeRrc'))
        for name in ('ReportUeMeasurements','DlDataSinr','DlCtrlSinr'):
            expected.add(('UE',r['node_id'],u,r['imsi'],'','0',name,'NrUePhy'))
    for c,r in cells.items():
        for name,source in (('SlotDataStats','NrGnbPhy'),('RxFromS1u','NrEpcGnbApplication'),('HandoverEndOk','NrGnbRrc'),('RecvMeasurementReport','NrGnbRrc'),('HandoverFailureNoPreamble','NrGnbRrc'),('HandoverFailureMaxRach','NrGnbRrc'),('HandoverFailureLeaving','NrGnbRrc'),('HandoverFailureJoining','NrGnbRrc')):
            expected.add(('gNB',r['node_id'],'','',c,'0',name,source))
    if len(traces)!=len(expected) or actual!=expected:
        raise ValueError('Trace registry duplicate/missing/wrong binding')
    settings=list(rows(run,'radio_settings_v3.csv'))
    setting_keys={(r['scope'],r['id'],r['attribute']) for r in settings}
    expected_settings=set()
    for c in cells:
        for name in ('Numerology','TxPower','NoiseFigure','Pattern'):expected_settings.add(('gNB',c,name))
        for name in ('RsrpFilterCoefficient','RsrqFilterCoefficient'):expected_settings.add(('gNB_RRC',c,name))
    for u in registry:
        for name in ('TxPower','NoiseFigure','UeMeasurementsFilterPeriod'):expected_settings.add(('UE',u,name))
    for scope,n in (('gNB_array',3),('UE_array',5)):
        for i in range(n):
            for name in ('NumRows','NumColumns','BearingAngle','DowntiltAngle'):expected_settings.add((scope,str(i),name))
            expected_settings.add((scope+'_element',str(i),'Gain'))
    expected_settings.update({('channel','0','Frequency'),('channel','0','ShadowingEnabled'),('condition','0','UpdatePeriod'),('fading','0','UpdatePeriod')})
    if len(settings)!=len(expected_settings) or setting_keys!=expected_settings:
        raise ValueError('Missing/duplicate effective settings')
    for r in settings:
        explicit=(r['scope']=='gNB' and r['attribute'] in ('Numerology','TxPower')) or (r['scope']=='channel' and r['attribute']=='Frequency')
        if not r['object_type'].startswith('ns3::') or not r['value'] or r['origin']!=('explicit' if explicit else 'library_default'):
            raise ValueError('Effective setting provenance mismatch')
    summaries = list(rows(run,'udp_summary_v3.csv')); summary=unique_registry(summaries,'ue_id',5)
    for s in summaries:
        identity(s,registry)
    packets = list(rows(run,'udp_packets_v3.csv'))
    received = packet_accounting(packets,registry,summary)
    for p in packets:
        if p['cell_id'] not in cells or int(p['rnti'])<=0 or ns(p['time_s'])>end:
            raise ValueError('Packet cell/RNTI/time')
        sent=ns(p['tx_time_s'])
        if not 1_000_000_000 <= sent < end-1_000_000_000 or sent != 1_000_000_000+int(p['sequence'])*10_000_000:
            raise ValueError('Packet TX grid mismatch')
    events = list(rows(run,'handover_events_v3.csv')); intervals=handovers(events,registry,require_gnb_completion=not allow_pending)
    current={u:r['initial_cell_id'] for u,r in registry.items()}; attempt=Counter()
    for e in events:
        u=identity(e,registry)
        if ns(e['time_s'])>end or e['source_cell_id'] not in cells or e['target_cell_id'] not in cells or int(e['rnti'])<=0:
            raise ValueError('Handover cell/time/RNTI')
        if e['event']=='UE_HandoverStart':
            attempt[u]+=1
            if int(e['attempt_id'])!=attempt[u] or e['source_cell_id']!=current[u] or e['source_cell_id']==e['target_cell_id']:
                raise ValueError('Broken handover source/attempt chain')
        if e['event']=='UE_HandoverEndOk':
            current[u]=e['target_cell_id']
    mobility=list(rows(run,'ue_mobility_v3.csv')); history=defaultdict(list)
    for r in mobility:
        u=identity(r,registry); t=ns(r['time_s']);history[u].append(t)
        position,velocity=trajectory(registry[u],t/1e9,turn)
        if r['valid']!='1' or any(not math.isclose(finite(r[a+'_m']),p,abs_tol=1e-7) or not math.isclose(finite(r['v'+a+'_mps']),v,abs_tol=1e-8) for a,p,v in zip('xyz',position,velocity)):
            raise ValueError('Piecewise mobility mismatch')
        if not math.isclose(finite(r['speed_mps']),math.sqrt(sum(v*v for v in velocity)),abs_tol=1e-8):
            raise ValueError('Mobility speed mismatch')
    times=list(range(0,end+1,step))
    if any(history[u]!=times for u in registry):
        raise ValueError('Incomplete mobility grid')
    serving=list(rows(run,'serving_cells_v3.csv')); sh=defaultdict(list)
    for r in serving:
        u=identity(r,registry);sh[u].append(ns(r['time_s']))
        if r['connected'] not in ('0','1') or (r['connected']=='1' and (r['cell_id'] not in cells or int(r['rnti'])<=0)):
            raise ValueError('Serving state/cell/RNTI')
        expected_cell=registry[u]['initial_cell_id']; in_attempt=False
        for h in intervals[u]:
            if h['start_s']<=float(r['time_s'])<=h['end_s']:in_attempt=True
            if float(r['time_s'])>h['end_s']:expected_cell=h['target']
        if r['connected']=='1' and not in_attempt and r['cell_id']!=expected_cell:
            raise ValueError('Serving history disagrees with handover')
    if any(sh[u]!=times for u in registry):
        raise ValueError('Incomplete serving grid')
    radio=list(rows(run,'radio_measurements.csv')); seen=set(); radio_counts=Counter(); prior={}
    for r in radio:
        u=identity(r,registry); t=ns(r['time_s']);finite(r['value'])
        if int(r['time_ns'])!=t:raise ValueError('Radio timestamp/unit mismatch')
        if t>end or r['measured_cell_id'] not in cells or r['bwp_id']!='0' or r['serving_cell_id'] not in cells:
            raise ValueError('Radio identity/time')
        if r['is_serving'] not in ('0','1') or (r['is_serving']=='1')!=(r['measured_cell_id']==r['serving_cell_id']):
            raise ValueError('Radio serving flag mismatch')
        if r['metric'] not in ('rsrp','rsrq_model_derived') or r['unit']!=('dBm' if r['metric']=='rsrp' else 'dB') or r['source']!='NrUePhy::ReportUeMeasurements':
            raise ValueError('Radio units/source')
        sig=tuple(r.values()); key=(u,r['metric'],r['measured_cell_id'])
        if sig in seen or t<prior.get(key,-1):raise ValueError('Duplicate/unordered radio')
        seen.add(sig);prior[key]=t;radio_counts[(u,r['metric'])]+=1
    metric_pairs=defaultdict(set)
    for r in radio:
        metric_pairs[tuple(r[k] for k in ('time_ns','ue_id','bwp_id','serving_cell_id','measured_cell_id','is_serving'))].add(r['metric'])
    if any(pair!={'rsrp','rsrq_model_derived'} for pair in metric_pairs.values()):raise ValueError('Unpaired RSRP/RSRQ epoch')
    candidates,coverage=candidate_rows(radio,registry,cells)
    # Enforce the SINR CSV's exact schema through both the contract reader and native parser.
    for _ in rows(run,'sinr_measurements.csv'):pass
    sinr=load_sinr(run/'sinr_measurements.csv'); sc=Counter();seen=set()
    for r in sinr:
        u=identity(r,registry)
        if r['cell_id'] not in cells or r['bwp_id']!='0' or r['ns']>end:
            raise ValueError('SINR cell/time/BWP')
        sig=tuple(r[k] for k in SCHEMAS['sinr_measurements.csv'])
        if sig in seen:raise ValueError('Duplicate SINR')
        seen.add(sig);sc[(u,r['channel_type'])]+=1
    reports=list(rows(run,'rrc_measurements_v3.csv'))
    report_signatures=set()
    for r in reports:
        if tuple(r.values()) in report_signatures:raise ValueError('Duplicate RRC report row')
        report_signatures.add(tuple(r.values()))
        identity(r,registry)
        if ns(r['time_s'])>end or r['serving_cell_id'] not in cells or r['neighbour_cell_id'] not in cells or r['serving_cell_id']==r['neighbour_cell_id'] or not all(0<=int(r[k])<=97 for k in ('serving_rsrp_ie','neighbour_rsrp_ie')):
            raise ValueError('RRC measurement identity/quantization')
    for u,hs in intervals.items():
        last=0
        for i,h in enumerate(hs):
            matching=[r for r in reports if r['ue_id']==u and r['serving_cell_id']==h['source'] and r['neighbour_cell_id']==h['target'] and r['rnti']==h['source_rnti'] and last<=float(r['time_s'])<=h['start_s']]
            if not matching:raise ValueError('HO lacks native preceding target report')
            h['rrc_report_time_s']=max(float(r['time_s']) for r in matching);last=h['end_s']
            limit=hs[i+1]['start_s'] if i+1<len(hs) else duration
            post=[r for r in sinr if r['ue_id']==u and h['end_s']<r['t']<limit]
            h['post_ue_end_sinr_channels']=sorted({r['channel_type'] for r in post})
            if (h['gnb_completed'] and {r['channel_type'] for r in post}!={'DL_DATA','DL_CONTROL'}) or any(r['cell_id']!=h['target'] for r in post):
                raise ValueError('Post-HO SINR attribution/coverage')
    fm=list(rows(run,'flow_monitor_v3.csv'))
    if len(fm)!=5 or {r['ue_id'] for r in fm}!=set(registry) or len({r['flow_monitor_id'] for r in fm})!=5 or len({r['source_ip'] for r in fm})!=1:
        raise ValueError('FlowMonitor mapping cardinality')
    for f in fm:
        u=f['ue_id']; r=registry[u]; s=summary[u]
        if f['destination_ip']!=r['ipv4'] or f['destination_port']!=r['destination_port'] or f['protocol']!='17':
            raise ValueError('FlowMonitor tuple mismatch')
        if any(f[k]!=s[k] for k in ('tx_packets','rx_packets')) or int(f['tx_ip_bytes'])!=540*int(f['tx_packets']) or int(f['rx_ip_bytes'])!=540*int(f['rx_packets']):
            raise ValueError('FlowMonitor/application mismatch')
        if int(f['lost_packets'])<0 or int(f['unresolved_packets'])<0 or int(f['tx_packets'])-int(f['rx_packets'])!=int(f['lost_packets'])+int(f['unresolved_packets']):
            raise ValueError('FlowMonitor classified/unresolved mismatch')
    for u,s in summary.items():
        if int(s['tx_packets'])!=math.ceil((duration-2)*100) or int(s['rx_packets'])<=0 or s['active_attempt']!='0' or int(s['ho_errors']) or s['final_cell_id']!=current[u]:
            raise ValueError('Invalid D2 final summary')
        if any(int(s[k])!=len(intervals[u]) for k in ('ho_starts','ho_ends')) or int(s['gnb_ends'])!=sum(h['gnb_completed'] for h in intervals[u]):
            raise ValueError('HO summary mismatch')
        final=[r for r in serving if r['ue_id']==u][-1]
        if final['connected']!='1' or final['cell_id']!=current[u]:raise ValueError('Final RRC state mismatch')
        if any(sc[(u,k)]==0 for k in ('DL_DATA','DL_CONTROL')) or any(radio_counts[(u,k)]==0 for k in ('rsrp','rsrq_model_derived')):
            raise ValueError('Missing per-UE PHY stream')
    failures=list(rows(run,'gnb_failures_v3.csv'))
    allowed_failures={'HandoverFailureNoPreamble','HandoverFailureMaxRach','HandoverFailureLeaving','HandoverFailureJoining'}
    signatures=set()
    for f in failures:
        identity(f,registry);signature=tuple(f.values())
        if ns(f['time_s'])>end or f['cell_id'] not in cells or int(f['rnti'])<=0 or f['event'] not in allowed_failures or signature in signatures:
            raise ValueError('Invalid native gNB failure evidence')
        signatures.add(signature)
    link_failures(failures,intervals)
    contexts=list(rows(run,'gnb_context_v3.csv'));context_map=unique_registry(contexts,'ue_id',5)
    context_issues=[]
    for u,c in context_map.items():
        identity(c,registry)
        if not end<=ns(c['time_s'])<=end+1 or c['cell_id']!=summary[u]['final_cell_id'] or c['gnb_context_present'] not in ('0','1') or c['ue_rrc_state']!='9':
            raise ValueError('Invalid final gNB/UE context snapshot')
        if int(c['pending_gnb_completions'])!=len(intervals[u])-sum(h['gnb_completed'] for h in intervals[u]):
            raise ValueError('Pending gNB completion counter mismatch')
        if c['gnb_context_present']=='0':
            if c['gnb_imsi'] or c['gnb_rrc_state']:raise ValueError('Absent gNB context has invented fields')
            context_issues.append(dict(ue_id=u,issue='missing_gNB_context',cell_id=c['cell_id'],rnti=c['rnti']))
        elif c['gnb_imsi']!=registry[u]['imsi'] or c['gnb_rrc_state']!='4':
            context_issues.append(dict(ue_id=u,issue='gNB_context_identity_or_state',snapshot=c))
    pending=[dict(ue_id=u,attempt_id=h['attempt_id'],source=h['source'],target=h['target']) for u,hs in intervals.items() for h in hs if not h['gnb_completed']]
    if not allow_pending and (failures or context_issues or pending):raise ValueError('Native handover/context health gate failed')
    prb,prb_bins=validate_slots(rows(run,'prb_slots_v3.csv'),cells,end,allow_bootstrap_gap=True)
    cell_qos,qos_bins,qos_packets=ingress_qos(rows(run,'cell_ingress_v3.csv'),packets,registry,cells,end,allow_unattributed=allow_pending)
    unattributed=cell_qos.pop('_unattributed',[])
    if sum(t['undelivered'] for t in cell_qos.values())+len(unattributed)!=sum(int(s['lost_unique']) for s in summary.values()):raise ValueError('Cell/unattributed loss conservation')
    result=dict(status='BLOCKED_NATIVE_HANDOVER' if failures or context_issues or pending or unattributed else 'VALIDATED_SINGLE_RUN',
                unattributed_tx_without_ingress=len(unattributed),native_failures=failures,final_context_issues=context_issues,pending_gnb_completions=pending,duration_s=duration,config=config,input_sha256=hashes,
                simultaneous_two_neighbour_epochs=coverage,prb=prb,cell_qos=cell_qos,
                ues={u:dict(tx=int(s['tx_packets']),rx=int(s['rx_packets']),undelivered=int(s['lost_unique']),
                            final_cell=s['final_cell_id'],handovers=intervals[u]) for u,s in summary.items()},
                radio_rows=len(radio),sinr_rows=len(sinr),sinr_invalid_rows=sum(r['db'] is None for r in sinr))
    return result,dict(candidates=candidates,prb_bins=prb_bins,qos_bins=qos_bins,qos_packets=qos_packets,
                       cells=cells,serving=serving,registry=registry,unattributed=unattributed)


def write_csv(out,name,records,fields):
    """Exclusively create a derived CSV with an explicit schema."""
    with (out/name).open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(records)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--compare-run',type=Path)
    parser.add_argument('--diagnostic',action='store_true',help='Permit failure evidence reports; native failures never become PASS')
    args=parser.parse_args()
    try:
        if args.output_dir.exists():raise ValueError('Choose fresh analysis directory')
        result,data=validate(args.run_dir,allow_pending=args.diagnostic)
        if args.compare_run:
            if args.compare_run.resolve()==args.run_dir.resolve():raise ValueError('Repeat run must be a distinct directory')
            other,_=validate(args.compare_run,allow_pending=args.diagnostic)
            if result['input_sha256']!=other['input_sha256']:raise ValueError('Same-seed raw CSV repeatability failed')
            manifests=[json.loads((p/'run_manifest.json').read_text()) for p in (args.run_dir,args.compare_run)]
            if any(m['returncode']!=(1 if result['status']=='BLOCKED_NATIVE_HANDOVER' else 0) or not m['files_unchanged_during_run'] for m in manifests):raise ValueError('Invalid execution provenance')
            if manifests[0]['source_binary_library_sha256']!=manifests[1]['source_binary_library_sha256']:raise ValueError('Repeat runs used different sources/binaries/libraries')
            result['execution_provenance']=[{k:m[k] for k in ('elapsed_s','max_rss_kib','output_bytes','resource_limits','rng_policy')} for m in manifests]
            result['repeatability']='ALL_RAW_CSV_BYTE_IDENTICAL'
            if not any(u['handovers'] for u in result['ues'].values()):raise ValueError('Full gate requires observed native HO lifecycle')
            if result['status']=='VALIDATED_SINGLE_RUN':result['status']='PASS'
        args.output_dir.mkdir(parents=True,exist_ok=False)
        write_csv(args.output_dir,'candidates_v3.csv',data['candidates'],
                  'time_s ue_id imsi bwp_id serving_cell_id candidate_cell_id measured rsrp_dbm rank source'.split())
        write_csv(args.output_dir,'qos_packets_v3.csv',data['qos_packets'],
                  'time_s ue_id imsi flow_id sequence ingress_cell_id ingress_time_s rx_rrc_cell_id udp_bytes delay_ms attribution'.split())
        write_csv(args.output_dir,'unattributed_packets_v3.csv',data['unattributed'],
                  'ue_id imsi flow_id sequence tx_time_s udp_bytes reason'.split())
        prb_rows=[];qos_rows=[];population=[];end=ns(result['config']['duration_s'])
        for start in range(0,end,100_000_000):
            stop=min(start+100_000_000,end)
            for c in data['cells']:
                used,available,slots=data['prb_bins'].get((start//100_000_000,c),(0,0,0))
                prb_rows.append(dict(window_start_s=start/1e9,window_end_s=stop/1e9,cell_id=c,bwp_id=0,
                                     allocated_prb_symbols=used,available_prb_symbols=available,observed_slots=slots,
                                     expected_slots=(stop-start)//500_000,
                                     observed_allocation_fraction=used/available if available else '',
                                     allocation_fraction=used/available if available and slots==(stop-start)//500_000 else '',
                                     valid=int(available>0 and slots==(stop-start)//500_000),
                                     scope='UL_DL_DATA_MSG3'))
                ps=data['qos_bins'].get((start//100_000_000,c),[]);b=sum(p[0] for p in ps)
                qos_rows.append(dict(window_start_s=start/1e9,window_end_s=stop/1e9,ingress_cell_id=c,
                                     rx_packets=len(ps),rx_bytes=b,goodput_mbps=8*b/((stop-start)*1e-9*1e6),
                                     mean_delay_ms=statistics.fmean(p[1] for p in ps) if ps else '',delay_valid=int(bool(ps)),
                                     attribution='S1U_ingress_cohort'))
        population_by_time=defaultdict(Counter)
        for r in data['serving']:
            if r['connected']=='1':population_by_time[r['time_s']][r['cell_id']]+=1
        for r in data['serving']:
            if r['ue_id']=='0':
                t=r['time_s']
                counts=population_by_time[t]
                for c in data['cells']:population.append(dict(time_s=t,cell_id=c,connected_ues=counts[c],source='sampled_UE_RRC_state'))
        write_csv(args.output_dir,'cell_prb_v3.csv',prb_rows,'window_start_s window_end_s cell_id bwp_id allocated_prb_symbols available_prb_symbols observed_slots expected_slots observed_allocation_fraction allocation_fraction valid scope'.split())
        write_csv(args.output_dir,'cell_qos_v3.csv',qos_rows,'window_start_s window_end_s ingress_cell_id rx_packets rx_bytes goodput_mbps mean_delay_ms delay_valid attribution'.split())
        write_csv(args.output_dir,'cell_population_v3.csv',population,'time_s cell_id connected_ues source'.split())
        if sum(r['rx_bytes'] for r in qos_rows)!=sum(u['rx']*512 for u in result['ues'].values()):raise ValueError('Derived QoS byte conservation')
        if any(not 0<=r['connected_ues']<=5 for r in population):raise ValueError('Derived population range')
        if any(r['observed_slots']<=0 or not 0<=r['observed_allocation_fraction']<=1 or (r['valid']==0 and r['window_start_s']!=0) or (r['valid']==0 and r['allocation_fraction']!='') for r in prb_rows):raise ValueError('Derived PRB window coverage')
        for name in ('candidates_v3.csv','qos_packets_v3.csv','cell_prb_v3.csv','cell_qos_v3.csv','cell_population_v3.csv','unattributed_packets_v3.csv'):
            with (args.output_dir/name).open(newline='') as stream:
                reader=csv.DictReader(stream)
                if len(reader.fieldnames)!=len(set(reader.fieldnames)):raise ValueError('Duplicate derived columns')
                for row in reader:
                    if None in row or any(v is None for v in row.values()):raise ValueError('Malformed derived CSV')
        result['derived_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output_dir.glob('*.csv')}
        if any(hashlib.sha256((args.run_dir/n).read_bytes()).hexdigest()!=h for n,h in result['input_sha256'].items()):raise ValueError('Input changed during analysis')
        result['analysis_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),Path(__file__).with_name('d2_schemas.json'),Path(__file__).with_name('phase_c22_sinr.py'))}
        (args.output_dir/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
        if result['status']=='BLOCKED_NATIVE_HANDOVER':raise SystemExit(2)
    except (ValueError,KeyError,OSError,ArithmeticError) as exc:
        parser.exit(1,f'FAIL: {exc}\n')


if __name__=='__main__':main()
