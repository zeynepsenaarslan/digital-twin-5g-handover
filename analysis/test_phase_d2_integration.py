"""Read-only integration checks against D2_RUN_DIR; GPL-2.0-only."""
import csv
import os
from pathlib import Path
import tempfile
import unittest

from phase_d2 import validate


@unittest.skipUnless(os.environ.get('D2_RUN_DIR'),'Set D2_RUN_DIR to a validated raw run')
class D2Integration(unittest.TestCase):
    def setUp(self):
        self.run=Path(os.environ['D2_RUN_DIR']).resolve()

    def mutate(self,name,change):
        """Link read-only evidence; replace only the corrupted copy in a temp dir."""
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)
            for source in self.run.iterdir():
                if source.is_file():(run/source.name).symlink_to(source)
            with (self.run/name).open(newline='') as stream:
                reader=csv.DictReader(stream);fields=reader.fieldnames;data=list(reader)
            change(data)
            target=run/name;target.unlink()
            with target.open('x',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(data)
            with self.assertRaises(ValueError):validate(run)

    def test_native_dataset(self):
        result,_=validate(self.run)
        self.assertEqual(result['status'],'VALIDATED_SINGLE_RUN')
        self.assertEqual(len(result['ues']),5)
        self.assertTrue(all(n>0 for n in result['simultaneous_two_neighbour_epochs'].values()))

    def test_wrong_trace_binding(self):
        self.mutate('trace_registry_v3.csv',lambda data:data[0].update(cell_id='999'))

    def test_missing_x2_pair(self):
        self.mutate('x2_registry_v3.csv',lambda data:data.pop())

    def test_wrong_initial_attachment(self):
        self.mutate('ue_registry_v3.csv',lambda data:data[0].update(initial_cell_id='999'))

    def test_motion_sign_corruption(self):
        self.mutate('ue_mobility_v3.csv',lambda data:data[-1].update(vx_mps='5'))

    def test_wrong_ingress_cell(self):
        self.mutate('cell_ingress_v3.csv',lambda data:data[0].update(cell_id='999'))

    def test_missing_radio_metric(self):
        self.mutate('radio_measurements.csv',lambda data:data.pop())

    def test_duplicate_sinr_callback(self):
        self.mutate('sinr_measurements.csv',lambda data:data.append(data[-1].copy()))

    def test_summary_count_corruption(self):
        self.mutate('udp_summary_v3.csv',lambda data:data[0].update(rx_packets='1'))


if __name__=='__main__':unittest.main()
