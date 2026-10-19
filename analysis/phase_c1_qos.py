#!/usr/bin/env python3
"""Analyze the existing ns-3 UDP CSV producer without running the simulator.

Only the Python standard library is required. Times are converted to integer ns
before comparisons/binning. Producer contract: one UdpClient, sequences starting
at zero and incremented on successful Send, constant packet size, no sequence wrap.
"""

import argparse
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import statistics


NS = 1_000_000_000


def ns(value):
    """Parse an exact, finite, nonnegative timestamp in seconds."""
    number = Decimal(str(value)) * NS
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise ValueError(f"Invalid nanosecond timestamp: {value}")
    return int(number)


def rows(path, required):
    """Read each schema independently and reject absent fields."""
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"Missing required columns in {path}: {sorted(required)}")
        return list(reader)


def mean(values):
    return statistics.fmean(values) if values else None


def maximum(values):
    return max(values) if values else None


def packet_stats(packets):
    """Summarize actual receptions, including duplicate reception events."""
    variations = [p['abs_delay_variation_ms'] for p in packets
                  if p['abs_delay_variation_ms'] is not None]
    gaps = [p['interarrival_gap_ms'] for p in packets
            if p['interarrival_gap_ms'] is not None]
    return dict(rx_packets=len(packets), rx_unique_packets=len({p['sequence'] for p in packets}),
                rx_bytes=sum(p['udp_bytes'] for p in packets),
                mean_delay_ms=mean([p['delay_ms'] for p in packets]),
                min_delay_ms=min((p['delay_ms'] for p in packets), default=None),
                max_delay_ms=maximum([p['delay_ms'] for p in packets]),
                mean_abs_delay_variation_ms=mean(variations),
                delay_variation_samples=len(variations), max_interarrival_gap_ms=maximum(gaps))


def analyze(directory, window_ns):
    """Validate source accounting and return derived packet/window/summary data."""
    if window_ns <= 0:
        raise ValueError("Analysis window must be positive")
    directory = Path(directory).resolve()
    traffic = rows(directory / 'udp_traffic.csv',
                   {'time_s', 'tx_packets', 'rx_packets', 'rx_bytes'})
    mobility = rows(directory / 'ue_mobility.csv',
                    {'time_s', 'ue_id', 'x_m', 'y_m', 'z_m', 'speed_mps'})
    raw = rows(directory / 'udp_packets.csv',
               {'rx_time_s', 'sequence', 'tx_time_s', 'udp_bytes'})
    events = rows(directory / 'handover_events.csv',
                  {'time_s', 'event', 'imsi', 'source_cell_id', 'target_cell_id', 'rnti'})
    if not traffic or not mobility:
        raise ValueError("Traffic and mobility observations must not be empty")
    traffic_times = [ns(r['time_s']) for r in traffic]
    mobility_times = [ns(r['time_s']) for r in mobility]
    if traffic_times != sorted(traffic_times) or mobility_times != sorted(mobility_times):
        raise ValueError("Source timestamps are not nondecreasing")
    end_ns = traffic_times[-1]
    if end_ns <= 0 or mobility_times[-1] != end_ns:
        raise ValueError("Final mobility and traffic observation times must agree")
    previous_counts = (0, 0, 0)
    if traffic_times[0] != 0 or mobility_times[0] != 0:
        raise ValueError("Full-run analysis requires observations beginning at time zero")
    for r in traffic:
        counts = tuple(int(r[k]) for k in ('tx_packets', 'rx_packets', 'rx_bytes'))
        if any(a < b for a, b in zip(counts, previous_counts)):
            raise ValueError("Cumulative traffic counters decreased")
        previous_counts = counts
    tx_count, authoritative_rx, authoritative_bytes = previous_counts

    packets, seen = [], {}
    previous_rx, previous_delay = None, None
    for r in raw:
        rx, tx = ns(r['rx_time_s']), ns(r['tx_time_s'])
        sequence, size = int(r['sequence']), int(r['udp_bytes'])
        if not (0 <= sequence < tx_count) or size <= 0:
            raise ValueError("Packet violates zero-based successful-send sequence contract")
        if tx > rx or rx > end_ns or (previous_rx is not None and rx < previous_rx):
            raise ValueError("Negative delay or unordered/out-of-range packet timestamp")
        if sequence in seen and seen[sequence] != (tx, size):
            raise ValueError("Conflicting records for the same sequence")
        delay = (rx - tx) / 1e6
        packets.append(dict(run_id=directory.name, sequence=sequence,
                            tx_time_s=f'{tx / NS:.9f}', rx_time_s=f'{rx / NS:.9f}',
                            udp_bytes=size, delay_ms=delay,
                            interarrival_gap_ms=None if previous_rx is None else (rx-previous_rx)/1e6,
                            abs_delay_variation_ms=None if previous_delay is None else abs(delay-previous_delay),
                            is_duplicate=int(sequence in seen), rx_ns=rx))
        seen[sequence] = (tx, size)
        previous_rx, previous_delay = rx, delay
    if len(packets) != authoritative_rx or sum(p['udp_bytes'] for p in packets) != authoritative_bytes:
        raise ValueError("Packet log disagrees with authoritative reception counters")

    # Confirm every cumulative RX snapshot, not just the final row.
    index, snapshot_bytes = 0, 0
    for r, t in zip(traffic, traffic_times):
        # Same-timestamp event ordering can place a reception after the snapshot.
        while index < len(packets) and packets[index]['rx_ns'] < t:
            snapshot_bytes += packets[index]['udp_bytes']
            index += 1
        tied = [p for p in packets[index:] if p['rx_ns'] == t]
        observed = int(r['rx_packets'])
        if not index <= observed <= index + len(tied):
            raise ValueError("Intermediate RX packet counter disagrees with timestamps")
        expected_bytes = snapshot_bytes + sum(p['udp_bytes'] for p in tied[:observed-index])
        if int(r['rx_bytes']) != expected_bytes:
            raise ValueError("Intermediate RX byte counter disagrees with packet log")

    intervals, active, incomplete = [], {}, []
    previous_event = -1
    for event in events:
        t = ns(event['time_s'])
        if not previous_event <= t <= end_ns:
            raise ValueError("Handover timestamps are unordered or out of range")
        previous_event = t
        imsi, label = event['imsi'], event['event']
        if label == 'UE_HandoverStart':
            if imsi in active:
                raise ValueError("Overlapping UE handover starts")
            active[imsi] = (t, event)
        elif label in ('UE_HandoverEndOk', 'UE_HandoverEndError'):
            if imsi not in active:
                raise ValueError("UE handover termination without a start")
            start, original = active.pop(imsi)
            if (event['source_cell_id'], event['target_cell_id']) != (
                    original['source_cell_id'], original['target_cell_id']):
                raise ValueError("Handover source/target identities disagree")
            intervals.append(dict(start_ns=start, end_ns=t, imsi=imsi,
                                  source_cell_id=original['source_cell_id'],
                                  target_cell_id=original['target_cell_id'],
                                  termination_event=label))
    incomplete = list(active)
    for packet in packets:
        t = packet['rx_ns']
        packet['handover_phase'] = ('unknown_incomplete_handover' if incomplete else
            'no_handover' if not intervals else
            'during' if any(h['start_ns'] <= t < h['end_ns'] for h in intervals) else
            'before' if t < intervals[0]['start_ns'] else
            'after' if t >= intervals[-1]['end_ns'] else 'between_handovers')

    window_count = (end_ns + window_ns - 1) // window_ns
    bins = [[] for _ in range(window_count)]
    for p in packets:
        bins[min(p['rx_ns'] // window_ns, window_count-1)].append(p)
    windows = []
    for i, group in enumerate(bins):
        start, stop = i*window_ns, min((i+1)*window_ns, end_ns)
        stats = packet_stats(group)
        windows.append(dict(run_id=directory.name, window_start_s=f'{start/NS:.9f}',
                            window_end_s=f'{stop/NS:.9f}', window_duration_s=(stop-start)/NS,
                            **stats, goodput_mbps=8*stats['rx_bytes']/((stop-start)/NS*1e6),
                            handover_overlap=int(any(start < h['end_ns'] and stop > h['start_ns']
                                                     for h in intervals))))
    missing = sorted(set(range(tx_count)) - set(seen))
    handovers = []
    for h in intervals:
        start, stop = h['start_ns'], h['end_ns']
        groups = {'before': [p for p in packets if p['rx_ns'] < start],
                  'during': [p for p in packets if start <= p['rx_ns'] < stop],
                  'after': [p for p in packets if p['rx_ns'] >= stop]}
        crossing = [p['interarrival_gap_ms'] for a, p in zip(packets, packets[1:])
                    if a['rx_ns'] <= stop and p['rx_ns'] >= start]
        handovers.append(dict(imsi=h['imsi'], source_cell_id=h['source_cell_id'],
                              target_cell_id=h['target_cell_id'],
                              start_time_s=f'{start/NS:.9f}', end_time_s=f'{stop/NS:.9f}',
                              termination_event=h['termination_event'],
                              ue_rrc_event_duration_ms=(stop-start)/1e6,
                              max_consecutive_rx_gap_overlapping_handover_ms=maximum(crossing),
                              receptions={name:packet_stats(group) for name,group in groups.items()}))
    summary = dict(run_id=directory.name, input_directory=str(directory), window_ms=window_ns/1e6,
                   observation_end_s=end_ns/NS, tx_packets_authoritative=tx_count,
                   **packet_stats(packets), duplicate_receptions=len(packets)-len(seen),
                   lost_unique_packets=tx_count-len(seen), missing_sequences=missing,
                   final_pdr=len(seen)/tx_count if tx_count else None,
                   final_pdr_percent=100*len(seen)/tx_count if tx_count else None,
                   observation_goodput_mbps=8*authoritative_bytes/(end_ns/NS*1e6),
                   producer_average_throughput_mbps=(
                       float(traffic[-1]['average_throughput_mbps'])
                       if traffic[-1].get('average_throughput_mbps') else None),
                   empty_windows=sum(not b for b in bins), handovers=handovers,
                   source_event_rows=events, incomplete_handover_imsis=incomplete,
                   validation={'packet_accounting':'PASS', 'nonnegative_delay':'PASS',
                               'timestamp_order':'PASS', 'intermediate_rx_snapshots':'PASS',
                               'window_byte_conservation':'PASS',
                               'handover_interval':'NOT VERIFIED' if incomplete or not intervals else 'PASS',
                               'loss_protocol_layer':'NOT VERIFIED',
                               'standardized_handover_interruption_time':'NOT VERIFIED'},
                   definitions={
                       'udp_bytes':'UDP payload including 12-byte SeqTsHeader; excludes UDP/IP/link headers',
                       'goodput':'Received recorded UDP bytes; not PHY/MAC throughput',
                       'delay':'(rx_time_s - tx_time_s) * 1000, ms, received packets only',
                       'delay_variation':'Absolute consecutive delay difference in reception order; not RFC 3550 jitter',
                       'window_assignment':'[start,end); final window includes observation-end receptions',
                       'window_gaps':'Consecutive global RX gap assigned to the window of the later reception',
                       'missing':'Final successful TX count minus unique RX, under zero-based contiguous UdpClient contract',
                       'nulls':'Undefined statistics are blank in CSV/null in JSON; empty goodput is measured zero',
                       'handover':'UE start/end traces; reception gaps are not standardized interruption time',
                       'duplicates':'All RX events count for bytes/goodput; only unique sequences count for final PDR',
                       'tx_records':'No per-packet records synthesized for missing packets',
                       'average_goodput':'observation_goodput uses [0, observation_end]; not B2 active-send denominator'},
                   input_sha256={name:hashlib.sha256((directory/name).read_bytes()).hexdigest()
                                 for name in ['udp_packets.csv','udp_traffic.csv',
                                              'handover_events.csv','ue_mobility.csv']})
    if sum(w['rx_bytes'] for w in windows) != authoritative_bytes:
        raise ValueError("Window bytes do not conserve received bytes")
    return packets, windows, summary


def write_csv(path, data, columns):
    with path.open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='New directory outside the input run; existing directories are refused')
    parser.add_argument('--window-ms', default='100', help='Positive window in ms (default: 100)')
    args = parser.parse_args()
    source, target = args.input_dir.resolve(), args.output_dir.resolve()
    try:
        if target == source or source in target.parents or target in source.parents:
            raise ValueError('Input and output directories must be separate, not nested')
        if target.exists():
            raise ValueError('Output directory already exists; choose a fresh directory')
        packets, windows, summary = analyze(source, ns(Decimal(args.window_ms)/1000))
        summary['analyzer_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        target.mkdir(parents=True, exist_ok=False)
        write_csv(target/'udp_packet_delay.csv', packets,
                  ['run_id','sequence','tx_time_s','rx_time_s','udp_bytes','delay_ms',
                   'interarrival_gap_ms','abs_delay_variation_ms','is_duplicate','handover_phase'])
        write_csv(target/'qos_timeseries.csv', windows, list(windows[0]))
        with (target/'qos_summary.json').open('x') as stream:
            json.dump(summary, stream, indent=2, allow_nan=False)
        report = ['# Phase C1 doğrulama raporu', '', f"Run: `{summary['run_id']}`",
                  f"Pencere: {summary['window_ms']} ms", '',
                  f"Başarılı TX: {summary['tx_packets_authoritative']}; benzersiz RX: {summary['rx_unique_packets']}; "
                  f"RX bayt: {summary['rx_bytes']}; eksik: {summary['lost_unique_packets']}", '',
                  '## Kontroller', '']
        report += [f'- {key}: **{value}**' for key,value in summary['validation'].items()]
        report += ['', '## Sayısal sonuçlar', '',
                   f"- Nihai PDR: {summary['final_pdr_percent']} %.",
                   f"- Eksik sequence: {summary['missing_sequences']}; duplicate RX: {summary['duplicate_receptions']}.",
                   f"- Ortalama gecikme: {summary['mean_delay_ms']} ms.",
                   f"- Ortalama mutlak gecikme değişimi: {summary['mean_abs_delay_variation_ms']} ms.",
                   f"- Tüm gözlem süresindeki ortalama received goodput: {summary['observation_goodput_mbps']} Mbit/s.",
                   f"- Kaynak CSV'deki gönderim penceresi ortalaması: {summary['producer_average_throughput_mbps']} Mbit/s.",
                   f"- Boş analiz penceresi: {summary['empty_windows']}.",
                   '- İlk paketin gap/variation alanları boş; boş pencerenin delay/variation alanları boş.',
                   '- Window TX-RX farkından kalıcı kayıp çıkarılmaz. Nihai kayıp yalnız gözlem sonundaki eksik teslimattır.']
        for handover in summary['handovers']:
            report += ['', '## Handover çevresi', '',
                       f"- UE başlangıç/bitiş: {handover['start_time_s']} / {handover['end_time_s']} s.",
                       f"- Source/target: {handover['source_cell_id']} / {handover['target_cell_id']}.",
                       f"- Gerçek termination trace: {handover['termination_event']}.",
                       f"- Handover ile kesişen ardışık RX boşluğu (maksimum): {handover['max_consecutive_rx_gap_overlapping_handover_ms']} ms."]
            for phase, values in handover['receptions'].items():
                report.append(f"- {phase}: {values['rx_packets']} RX paket, {values['rx_bytes']} bayt.")
        report += ['', '## Tanımlar ve sınırlar', '']
        report += [f'- {key}: {value}' for key,value in summary['definitions'].items()]
        report += ['', 'Kaynak CSV dosyaları değiştirilmedi. SHA-256 özetleri JSON içinde bulunur.',
                   'Bu çalışma radyo ölçümü veya yeni simülasyon çalıştırması içermez.',
                   'Tek handover sonucu genel algoritma güvenilirliğini kanıtlamaz.', '']
        with (target/'validation_report.md').open('x') as stream:
            stream.write('\n'.join(report))
        print(json.dumps({key:summary[key] for key in ['run_id','tx_packets_authoritative',
              'rx_unique_packets','rx_bytes','lost_unique_packets','final_pdr_percent',
              'mean_delay_ms','mean_abs_delay_variation_ms','observation_goodput_mbps']}, indent=2))
        print(f'Outputs: {target}')
    except (ValueError, OSError, ArithmeticError) as error:
        parser.exit(1, f'Analysis failed: {error}\n')


if __name__ == '__main__':
    main()
