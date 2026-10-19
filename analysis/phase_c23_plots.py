#!/usr/bin/env python3
"""Plot validated PHY and offline QoS CSVs without changing simulation data.

Radio metrics are registered below so future verified metrics can be added
without changing the loader/renderer. SINR is intentionally absent: C2.2 has
not been implemented. Points are never interpolated or forward-filled.
"""

import argparse
import csv
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path


RADIO_METRICS = {
    'rsrp': ('PHY RSRP', 'dBm'),
    'rsrq_model_derived': ('Model-derived RSRQ', 'dB'),
}
EVENTS = {
    'UE_HandoverStart': ('UE HO start', '#b2182b', '--'),
    'UE_HandoverEndOk': ('UE HO complete', '#2166ac', ':'),
    'gNB_HandoverEndOk': ('Target gNB HO complete', '#762a83', '-.'),
}


def read_csv(path, required, allow_empty=False):
    """Validate each input schema independently; never open inputs for writing."""
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f'{path}: missing columns {sorted(required-set(reader.fieldnames or []))}')
        data = list(reader)
    if not data and not allow_empty:
        raise ValueError(f'{path}: empty dataset')
    return data


def number(value, context, missing=False):
    if missing and value == '':
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'{context}: nonfinite number')
    return result


def ordered(values, context):
    if any(b < a for a,b in zip(values, values[1:])):
        raise ValueError(f'{context}: unordered times')


def load_data(radio_run, qos_dir):
    """Load typed records and prove QoS records correspond to this radio run."""
    paths = {'radio':radio_run/'radio_measurements.csv',
             'events':radio_run/'handover_events.csv',
             'packets':qos_dir/'udp_packet_delay.csv',
             'windows':qos_dir/'qos_timeseries.csv',
             'raw_packets':radio_run/'udp_packets.csv'}
    hashes = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()}
    radio = read_csv(paths['radio'], {'time_s','ue_id','imsi','bwp_id','serving_cell_id',
                      'measured_cell_id','is_serving','metric','value','unit','source'})
    streams = defaultdict(list)
    for r in radio:
        r['t'] = number(r['time_s'], 'radio time')
        r['v'] = number(r['value'], 'radio value', missing=True)
        if r['metric'] not in RADIO_METRICS:
            raise ValueError('Unregistered radio metric: add verified metadata before plotting')
        if r['source'] != 'NrUePhy::ReportUeMeasurements' or r['unit'] != RADIO_METRICS[r['metric']][1]:
            raise ValueError('Wrong radio source/unit: RRC encoded values are not PHY measurements')
        if r['is_serving'] not in ('0','1') or ((r['is_serving']=='1') !=
                (r['serving_cell_id']==r['measured_cell_id'])):
            raise ValueError('Invalid serving/neighbour attribution')
        if r['t'] < 0:
            raise ValueError('Negative radio time')
        key = tuple(r[k] for k in ('ue_id','imsi','bwp_id','measured_cell_id','metric'))
        streams[key].append(r['t'])
    for key,times in streams.items(): ordered(times,str(key))
    if len({(r['imsi'],r['bwp_id']) for r in radio}) != 1:
        raise ValueError('Select one UE/BWP before plotting this aligned figure set')
    for metric in RADIO_METRICS:
        if not any(r['metric']==metric and r['v'] is not None for r in radio):
            raise ValueError(f'No usable values for {metric}')

    packets = read_csv(paths['packets'], {'run_id','sequence','tx_time_s','rx_time_s','udp_bytes','delay_ms'})
    raw = read_csv(paths['raw_packets'], {'sequence','tx_time_s','rx_time_s','udp_bytes'})
    if len(raw) != len(packets): raise ValueError('QoS/raw packet count mismatch')
    for p,r in zip(packets,raw):
        if any(p[k] != r[k] for k in ('sequence','tx_time_s','rx_time_s','udp_bytes')):
            raise ValueError('QoS and radio run contain different packet records')
        p['t'] = number(p['rx_time_s'], 'RX time')
        p['delay'] = number(p['delay_ms'], 'delay', missing=True)
        if p['delay'] is not None and (p['delay'] < 0 or not math.isclose(
                p['delay'], (p['t']-number(p['tx_time_s'],'TX time'))*1000, abs_tol=1e-8)):
            raise ValueError('Delay does not match packet timestamps')
    ordered([p['t'] for p in packets], 'packets')
    if not any(p['delay'] is not None for p in packets): raise ValueError('Empty delay series')
    windows = read_csv(paths['windows'], {'run_id','window_start_s','window_end_s',
                       'window_duration_s','rx_bytes','rx_packets','goodput_mbps'})
    previous_end = None
    for w in windows:
        w['start'],w['end'] = (number(w[k], k) for k in ('window_start_s','window_end_s'))
        duration = number(w['window_duration_s'], 'window duration')
        w['g'] = number(w['goodput_mbps'], 'goodput', missing=True)
        if duration <= 0 or not math.isclose(w['end']-w['start'], duration, abs_tol=1e-9):
            raise ValueError('Invalid window duration')
        if previous_end is not None and w['start'] < previous_end-1e-9:
            raise ValueError('Overlapping or unordered windows')
        previous_end = w['end']
        if int(w['rx_bytes']) < 0 or int(w['rx_packets']) < 0:
            raise ValueError('Negative window counters')
        if w['g'] is not None and not math.isclose(w['g'],8*int(w['rx_bytes'])/duration/1e6,abs_tol=1e-9):
            raise ValueError('Goodput/bytes mismatch')
    if not any(w['g'] is not None for w in windows): raise ValueError('Empty goodput series')
    if sum(int(w['rx_bytes']) for w in windows) != sum(int(p['udp_bytes']) for p in packets):
        raise ValueError('Window/packet byte totals differ')
    if len({r['run_id'] for r in packets+windows}) != 1: raise ValueError('Mixed QoS run identifiers')
    events = read_csv(paths['events'], {'time_s','event','imsi','source_cell_id','target_cell_id','rnti'}, True)
    for e in events:
        e['t'] = number(e['time_s'],'event time')
        if not 0 <= e['t'] <= windows[-1]['end']: raise ValueError('Event outside observation')
    ordered([e['t'] for e in events], 'handover events')
    if events and not all(any(e['event']==name for e in events)
                          for name in ('UE_HandoverStart','UE_HandoverEndOk')):
        raise ValueError('Incomplete handover; cannot label successful aligned view')
    if max(r['t'] for r in radio) > windows[-1]['end']+1e-9:
        raise ValueError('Radio and QoS observation ranges disagree')
    return dict(radio=radio,packets=packets,windows=windows,events=events,hashes=hashes)


def mark_events(ax, events):
    """Use recorded timestamps; labels distinguish UE and target gNB completion."""
    used = set()
    for event in events:
        if event['event'] in EVENTS:
            label,color,style = EVENTS[event['event']]
            ax.axvline(event['t'], color=color, linestyle=style, linewidth=1,
                       label=label if label not in used else '_nolegend_', zorder=4)
            used.add(label)


def plot_radio(ax, data, metric, bounds=None):
    """Scatter only actual observations; color identifies cell, shape identifies role."""
    cells = sorted({r['measured_cell_id'] for r in data['radio']})
    counts = {}
    for i,cell in enumerate(cells):
        for role in ('1','0'):
            samples = [r for r in data['radio'] if r['metric']==metric and
                       r['measured_cell_id']==cell and r['is_serving']==role and r['v'] is not None
                       and (bounds is None or bounds[0]<=r['t']<=bounds[1])]
            if not samples: continue
            name = f"Cell {cell} - {'serving' if role=='1' else 'neighbour'}"
            ax.scatter([r['t'] for r in samples], [r['v'] for r in samples],
                       s=19 if bounds else 10, marker='o' if role=='1' else '^',
                       facecolors=f'C{i}' if role=='1' else 'none', edgecolors=f'C{i}',
                       linewidths=.7, label=name)
            counts[name] = len(samples)
    ax.set_ylabel(f'{RADIO_METRICS[metric][0]} ({RADIO_METRICS[metric][1]})')
    return counts


def render(data, output, zoom_seconds):
    """Render five figure families with a noninteractive backend."""
    os.environ['MPLCONFIGDIR'] = str(output/'.mplconfig')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10,
                         'axes.titlesize':12, 'legend.fontsize':8,
                         'svg.fonttype':'none', 'axes.spines.top':False,
                         'axes.spines.right':False})
    manifest = {'matplotlib_version':matplotlib.__version__, 'backend':matplotlib.get_backend(),
                'sinr':'NOT MEASURED; C2.2 not implemented', 'figures':{},
                'input_sha256':data['hashes'], 'handover_markers':data['events'],
                'data_counts':{k:len(data[k]) for k in ('radio','packets','windows','events')},
                'time_ranges_s':{'radio':[min(r['t'] for r in data['radio']),max(r['t'] for r in data['radio'])],
                                 'packets':[data['packets'][0]['t'],data['packets'][-1]['t']],
                                 'windows':[data['windows'][0]['start'],data['windows'][-1]['end']]}}

    def save(fig,name,axes,counts):
        for ax in axes:
            ax.grid(True,alpha=.22)
            ax.set_xlabel('Simulation time (s)')
            mark_events(ax,data['events'])
            ax.legend(loc='best',framealpha=.9)
        for extension in ('png','svg'):
            path = output/f'{name}.{extension}'
            if path.exists(): raise ValueError(f'Output exists: {path}')
            fig.savefig(path,dpi=300,metadata={'Description':'Actual recorded measurements; no interpolation'})
        manifest['figures'][name] = counts
        plt.close(fig)

    for metric,name,title in [('rsrp','rsrp','PHY RSRP observations'),
                              ('rsrq_model_derived','rsrq','Model-derived RSRQ observations')]:
        fig,ax = plt.subplots(figsize=(10,5),layout='constrained')
        counts = plot_radio(ax,data,metric)
        ax.set_title(title)
        save(fig,name,[ax],counts)
    fig,ax = plt.subplots(figsize=(10,5),layout='constrained')
    packets = [p for p in data['packets'] if p['delay'] is not None]
    ax.scatter([p['t'] for p in packets],[p['delay'] for p in packets],s=5,label='Received UDP packets')
    ax.set(ylabel='UDP end-to-end delay (ms)',title='Received UDP packet delay')
    save(fig,'udp_delay',[ax],{'packet_points':len(packets)})
    fig,ax = plt.subplots(figsize=(10,5),layout='constrained')
    windows = [w for w in data['windows'] if w['g'] is not None]
    ax.bar([w['start'] for w in windows],[w['g'] for w in windows],
           width=[w['end']-w['start'] for w in windows],align='edge',
           label='Recorded UDP payload goodput',linewidth=0)
    ax.set(ylabel='Received UDP goodput (Mbit/s)',title='Received application goodput per analysis window')
    save(fig,'udp_goodput',[ax],{'window_bars':len(windows)})
    starts = [e['t'] for e in data['events'] if e['event']=='UE_HandoverStart']
    ends = [e['t'] for e in data['events'] if e['event']=='UE_HandoverEndOk']
    if starts:
        bounds = (max(0,starts[0]-zoom_seconds), min(data['windows'][-1]['end'],ends[0]+zoom_seconds))
    else:
        bounds = (data['windows'][0]['start'],data['windows'][-1]['end'])
    fig,axes = plt.subplots(2,1,figsize=(10,7),sharex=True,layout='constrained')
    counts = plot_radio(axes[0],data,'rsrp',bounds)
    selected = [p for p in packets if bounds[0]<=p['t']<=bounds[1]]
    if not counts or not selected: raise ValueError('Zoom has no radio/delay observations; enlarge --zoom-seconds')
    axes[1].scatter([p['t'] for p in selected],[p['delay'] for p in selected],s=14,label='Received UDP packets')
    axes[1].set_ylabel('UDP end-to-end delay (ms)')
    axes[1].set_xlim(*bounds)
    axes[0].set_title('Time-aligned observations around first handover' if starts else 'Time-aligned observations (no recorded handover)')
    save(fig,'handover_aligned',axes,{'radio_points':counts,'packet_points':len(selected),'bounds_s':bounds})
    if not all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in data['hashes'].items()):
        raise ValueError('Input files changed during plotting')
    manifest['input_preservation'] = 'PASS'
    with (output/'plot_manifest.json').open('x') as stream: json.dump(manifest,stream,indent=2,allow_nan=False)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--radio-run',type=Path,required=True)
    parser.add_argument('--qos-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--zoom-seconds',type=float,default=1.0,
                        help='Seconds of context on each side of the first UE handover')
    args = parser.parse_args()
    try:
        output = args.output_dir.resolve()
        if output.exists(): raise ValueError('Output directory exists; select a fresh directory')
        for source in (args.radio_run.resolve(),args.qos_dir.resolve()):
            if source == output or source in output.parents or output in source.parents:
                raise ValueError('Output must be separate from source directories')
        if not math.isfinite(args.zoom_seconds) or args.zoom_seconds<=0: raise ValueError('Invalid zoom width')
        data = load_data(args.radio_run,args.qos_dir)
        output.mkdir(parents=True,exist_ok=False)
        manifest = render(data,output,args.zoom_seconds)
        report = ['# Phase C2.3 bilimsel görselleştirme', '',
                  f"Matplotlib: {manifest['matplotlib_version']}; backend: Agg; PNG: 300 DPI; SVG: vektör.",
                  f'Radyo kaynağı: `{args.radio_run}`; QoS kaynağı: `{args.qos_dir}`.', '',
                  f"Kayıt sayıları: {manifest['data_counts']}. Zaman aralıkları: {manifest['time_ranges_s']}.", '',
                  '- rsrp: PHY trace dBm değerleri; hücre renkleri ve serving/neighbour işaretleri ayrıdır.',
                  '- rsrq: kurulu modelden türetilmiş dB; bağımsız standart uygunluğu iddia edilmez.',
                  '- udp_delay: alınan paketlerin TX-RX zaman farkı, ms; alım boşluğu değildir.',
                  '- udp_goodput: mevcut analiz pencerelerinde alınan kayıtlı UDP baytları, Mbit/s.',
                  '- handover_aligned: aynı zaman ekseninde RSRP ve gecikme; ilk handover çevresindeki noktalar.', '',
                  '## Kaynak ve yorum sınırları', '',
                  'Noktalar gerçek kayıtlardır; enterpolasyon, forward-fill veya sentetik veri yoktur.',
                  'Boş sayısal alanlar eksik kabul edilir ve çizilmez; sayısal sıfır korunur.',
                  f"Eksik radio/delay/goodput değer sayısı: {sum(r['v'] is None for r in data['radio'])}/"
                  f"{sum(p['delay'] is None for p in data['packets'])}/{sum(w['g'] is None for w in data['windows'])}.",
                  'UDP yükü 12 bayt SeqTsHeader içerir; UDP/IP/link başlıkları hariçtir. PHY/MAC throughput değildir.',
                  'Handover çizgileri olay CSV’sindeki zamanlardır; UE ve hedef gNB bitişi ayrı gösterilir.',
                  '200 ms radyo örneklemesi milisaniyelik handover sürecini çözemez.',
                  'SINR ölçülmedi ve çizilmedi. RRC kuantize RSRP verisi kullanılmadı.',
                  'Grafikler handover ile gecikmenin zaman ilişkisini gösterir; kaybın katmanını veya nedenselliği kanıtlamaz.',
                  '30 s baseline ile 45 s deney karşılaştırmasından nedensel sonuç çıkarılmaz.', '',
                  '## Gerçek olay zamanları', '']
        report += [f"- {e['event']}: {e['time_s']} s, hücre {e['source_cell_id']} -> {e['target_cell_id']}" for e in data['events']]
        report += ['', 'PASS: QoS paket kayıtları radyo koşusunun özgün paket CSV’siyle eşleşir.',
                   'PASS: Şema, sonlu sayılar, birimler, roller, zaman sırası ve bayt/goodput tutarlılığı kontrol edildi.',
                   'PASS: Giriş SHA-256 özetleri değişmedi; her serinin nokta sayısı plot_manifest.json içindedir.', '']
        with (output/'report.md').open('x') as stream: stream.write('\n'.join(report))
        print(json.dumps({'output':str(output),'matplotlib':manifest['matplotlib_version'],
                          'counts':manifest['data_counts'],'figures':len(manifest['figures']),
                          'input_preservation':manifest['input_preservation']},indent=2))
    except (OSError,ValueError,KeyError,ImportError) as error:
        parser.exit(1,f'Plotting failed: {error}\n')


if __name__ == '__main__':
    main()
