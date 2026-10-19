"""Edge-case checks for offline QoS accounting and time boundaries."""

import csv
from pathlib import Path
import tempfile
import unittest

from phase_c1_qos import analyze


class OfflineQosTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.write('udp_packets.csv',
                   ['rx_time_s','sequence','tx_time_s','udp_bytes'],
                   [['0.2',0,'0.1',512], ['0.3',1,'0.2',512],
                    ['0.45',1,'0.2',512], ['0.5',2,'0.4',512]])
        self.write('udp_traffic.csv', ['time_s','tx_packets','rx_packets','rx_bytes'],
                   [[0,0,0,0], [1,4,4,2048]])
        self.write('ue_mobility.csv', ['time_s','ue_id','x_m','y_m','z_m','speed_mps'],
                   [[0,0,0,0,0,0], [1,0,0,0,0,0]])
        self.write('handover_events.csv',
                   ['time_s','event','imsi','source_cell_id','target_cell_id','rnti'],
                   [['0.4','UE_HandoverStart',1,1,2,1],
                    ['0.45','UE_HandoverEndOk',1,1,2,1]])

    def write(self, name, header, values):
        with (self.directory/name).open('w', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(values)

    def test_duplicate_empty_windows_and_exact_boundaries(self):
        packets, windows, summary = analyze(self.directory, 100_000_000)
        self.assertIsNone(packets[0]['abs_delay_variation_ms'])
        self.assertIsNone(packets[0]['interarrival_gap_ms'])
        self.assertEqual(packets[2]['is_duplicate'], 1)
        self.assertEqual(summary['rx_unique_packets'], 3)
        self.assertEqual(summary['duplicate_receptions'], 1)
        self.assertEqual(summary['rx_bytes'], 2048)
        self.assertEqual(summary['final_pdr'], .75)
        self.assertEqual(summary['missing_sequences'], [3])
        self.assertEqual(summary['mean_abs_delay_variation_ms'], 100)
        self.assertEqual(windows[0]['goodput_mbps'], 0)
        self.assertIsNone(windows[0]['mean_delay_ms'])
        self.assertEqual(windows[1]['rx_packets'], 0)
        self.assertEqual(windows[2]['rx_packets'], 1)
        self.assertEqual(packets[2]['handover_phase'], 'after')
        self.assertEqual(summary['handovers'][0]['receptions']['during']['rx_packets'], 0)
        self.assertEqual(sum(w['rx_bytes'] for w in windows), 2048)

    def test_short_final_window(self):
        _, windows, _ = analyze(self.directory, 300_000_000)
        self.assertEqual(len(windows), 4)
        self.assertAlmostEqual(windows[-1]['window_duration_s'], .1)

    def test_negative_delay_rejected(self):
        path = self.directory/'udp_packets.csv'
        path.write_text(path.read_text().replace('0.2,0,0.1', '0.2,0,0.25'))
        with self.assertRaisesRegex(ValueError, 'Negative delay'):
            analyze(self.directory, 100_000_000)

    def test_counter_mismatch_rejected(self):
        path = self.directory/'udp_traffic.csv'
        path.write_text(path.read_text().replace('1,4,4,2048', '1,4,4,999'))
        with self.assertRaisesRegex(ValueError, 'authoritative'):
            analyze(self.directory, 100_000_000)

    def test_out_of_order_receptions_rejected(self):
        path = self.directory/'udp_packets.csv'
        lines = path.read_text().splitlines()
        lines[2], lines[3] = lines[3], lines[2]
        path.write_text('\n'.join(lines)+'\n')
        with self.assertRaisesRegex(ValueError, 'unordered'):
            analyze(self.directory, 100_000_000)


if __name__ == '__main__':
    unittest.main()
