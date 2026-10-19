"""Small validation tests; no GUI or simulation is required."""

import csv
from pathlib import Path
import tempfile
import unittest

from phase_c23_plots import load_data, number, read_csv


class PlotInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_missing_columns(self):
        path = self.root/'data.csv'
        path.write_text('time_s\n1\n')
        with self.assertRaisesRegex(ValueError,'missing columns'):
            read_csv(path,{'time_s','value'})

    def test_empty_dataset(self):
        path = self.root/'data.csv'
        path.write_text('time_s,value\n')
        with self.assertRaisesRegex(ValueError,'empty dataset'):
            read_csv(path,{'time_s','value'})

    def test_invalid_values_and_missing_vs_zero(self):
        for value in ('nan','inf','-inf','garbage'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value,'measurement')
        self.assertIsNone(number('','measurement',missing=True))
        self.assertEqual(number('0','measurement',missing=True),0)

    def make_fixture(self, unit='dBm', value='-80'):
        radio = self.root/'radio'
        qos = self.root/'qos'
        radio.mkdir(); qos.mkdir()
        def write(path,header,values):
            with path.open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(header);writer.writerows(values)
        write(radio/'radio_measurements.csv',
              ['time_s','ue_id','imsi','bwp_id','serving_cell_id','measured_cell_id',
               'is_serving','metric','value','unit','source'],
              [[.2,0,2,0,1,1,1,'rsrp',value,unit,'NrUePhy::ReportUeMeasurements'],
               [.2,0,2,0,1,1,1,'rsrq_model_derived',-12,'dB','NrUePhy::ReportUeMeasurements']])
        write(radio/'handover_events.csv',
              ['time_s','event','imsi','source_cell_id','target_cell_id','rnti'],[])
        write(radio/'udp_packets.csv',['sequence','tx_time_s','rx_time_s','udp_bytes'],
              [[0,'.1','.2',512]])
        write(qos/'udp_packet_delay.csv',
              ['run_id','sequence','tx_time_s','rx_time_s','udp_bytes','delay_ms'],
              [['test',0,'.1','.2',512,100]])
        write(qos/'qos_timeseries.csv',
              ['run_id','window_start_s','window_end_s','window_duration_s','rx_bytes','rx_packets','goodput_mbps'],
              [['test',0,1,1,512,1,.004096]])
        return radio,qos

    def test_wrong_units_rejected(self):
        with self.assertRaisesRegex(ValueError,'source/unit'):
            load_data(*self.make_fixture(unit='encoded'))

    def test_nonfinite_radio_rejected(self):
        with self.assertRaisesRegex(ValueError,'nonfinite'):
            load_data(*self.make_fixture(value='nan'))

    def test_real_values_and_empty_event_table(self):
        data=load_data(*self.make_fixture())
        self.assertEqual(len(data['radio']),2)
        self.assertEqual(data['events'],[])
        self.assertAlmostEqual(data['windows'][0]['g'],.004096)

    def test_mismatched_run_rejected(self):
        radio,qos=self.make_fixture()
        path=qos/'udp_packet_delay.csv'
        path.write_text(path.read_text().replace('.1,.2,512','.1,.3,512'))
        with self.assertRaisesRegex(ValueError,'different packet records'):
            load_data(radio,qos)


if __name__ == '__main__':
    unittest.main()
