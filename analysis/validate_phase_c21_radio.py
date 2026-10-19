#!/usr/bin/env python3
"""Read-only checks of passive PHY CSVs and byte-for-byte B3/baseline regression."""

import argparse
import csv
from decimal import Decimal
import json
import math
from pathlib import Path


SCHEMA = ['time_ns', 'time_s', 'ue_id', 'imsi', 'rnti', 'bwp_id',
          'serving_cell_id', 'measured_cell_id', 'is_serving', 'metric',
          'value', 'unit', 'source']
LEGACY = ['ue_mobility.csv', 'udp_packets.csv', 'udp_traffic.csv',
          'handover_events.csv', 'handover_measurements.csv']


def read(path):
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def check(run, reference):
    """Raise ValueError on invalid data; do not modify either run directory."""
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    schema, rows = read(run/'radio_measurements.csv')
    require(schema == SCHEMA, 'Unexpected radio CSV schema')
    require(bool(rows), 'No actual radio measurements')
    streams, pairs, groups = {}, {}, {}
    for row in rows:
        time = int(row['time_ns'])
        require(Decimal(row['time_s'])*1_000_000_000 == time, 'Timestamp unit mismatch')
        require(time >= 0, 'Negative time')
        require(row['metric'] in ('rsrp', 'rsrq_model_derived'), 'Unexpected metric')
        require(row['unit'] == ('dBm' if row['metric'] == 'rsrp' else 'dB'), 'Wrong unit')
        require(math.isfinite(float(row['value'])), 'Nonfinite radio value')
        require(row['source'] == 'NrUePhy::ReportUeMeasurements', 'Wrong source')
        require(row['is_serving'] in ('0','1'), 'Invalid serving flag')
        require((row['is_serving'] == '1') ==
                (row['serving_cell_id'] == row['measured_cell_id']), 'Misattributed cell')
        require(row['measured_cell_id'] in ('1','2'), 'Unexpected cell for this two-cell scenario')
        require(row['ue_id'] == '0' and row['imsi'] == '2', 'Unexpected UE identity')
        require(row['bwp_id'] == '0' and int(row['rnti']) > 0, 'Invalid BWP/RNTI')
        key = tuple(row[k] for k in ('ue_id','imsi','bwp_id','measured_cell_id','metric'))
        require(time >= streams.get(key, -1), 'Nonmonotonic measurement stream')
        streams[key] = time
        pair = tuple(row[k] for k in SCHEMA[:9])
        require(row['metric'] not in pairs.setdefault(pair, set()), 'Duplicate metric sample')
        pairs[pair].add(row['metric'])
        group = (row['measured_cell_id'], row['serving_cell_id'], row['is_serving'], row['metric'])
        groups[group] = groups.get(group, 0) + 1
    require(all(len(pair) == 2 for pair in pairs.values()), 'Missing RSRP/RSRQ partner')
    for name in LEGACY:
        require((run/name).read_bytes() == (reference/name).read_bytes(), f'Regression: {name}')
    _, events = read(run/'handover_events.csv')
    _, traffic = read(run/'udp_traffic.csv')
    require(max(streams.values()) <= int(Decimal(traffic[-1]['time_s'])*1_000_000_000),
            'Measurement beyond simulation end')
    for event in events:
        if event['event'] == 'UE_HandoverEndOk':
            boundary = int(Decimal(event['time_s'])*1_000_000_000)
            target = event['target_cell_id']
            require(any(int(r['time_ns']) > boundary and r['serving_cell_id'] == target and
                        r['measured_cell_id'] == target and r['is_serving'] == '1' for r in rows),
                    'No target serving measurements after handover')
    require(any(r['is_serving'] == '1' for r in rows), 'No serving measurements')
    require(any(r['is_serving'] == '0' for r in rows), 'No actual neighbour measurements')
    return dict(status='PASS', run=str(run), reference=str(reference), radio_rows=len(rows),
                trace_observations=len(pairs), measurement_streams=len(streams),
                first_time_s=rows[0]['time_s'], last_time_s=rows[-1]['time_s'],
                attribution=[dict(measured_cell_id=k[0], serving_cell_id=k[1],
                                  is_serving=k[2], metric=k[3], rows=v) for k,v in sorted(groups.items())],
                legacy_csv_byte_identity='PASS', final_udp_counters=traffic[-1],
                handover_events=events)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--reference-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.run_dir, args.reference_dir), indent=2))
    except (ValueError, OSError, KeyError, ArithmeticError) as error:
        parser.exit(1, f'FAIL: {error}\n')


if __name__ == '__main__':
    main()
