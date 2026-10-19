"""SINR parser safety, conversion and actual-point plotting checks."""

import csv
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

from phase_c22_sinr import SCHEMA, load_sinr, render_sinr, summarize, validity


class SinrTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.path=self.root/'sinr.csv'

    def write(self, numbers):
        with self.path.open('w',newline='') as f:
            w=csv.writer(f);w.writerow(SCHEMA)
            for i,value in enumerate(numbers):
                status=validity(value)
                w.writerow([200000000+i*100000000,f'{.2+i*.1:.9f}',0,2,1,1,0,
                    'DL_DATA',repr(value),10*math.log10(value) if status=='ok' else '',
                    int(status=='ok'),status,'NrUePhy::DlDataSinr'])

    def test_linear_conversion(self):
        self.write([1,10,.1])
        self.assertEqual([r['db'] for r in load_sinr(self.path)],[0,10,-10])

    def test_invalid_values_retained_without_db(self):
        self.write([0,-1,float('nan'),float('inf'),sys.float_info.max])
        samples=load_sinr(self.path)
        self.assertTrue(all(s['db'] is None for s in samples))
        self.assertEqual(summarize(samples)['DL_DATA']['invalid'],5)

    def test_fabricated_invalid_db_rejected(self):
        self.write([0])
        text=self.path.read_text().replace(',0,,0,not_positive',',0,0,0,not_positive')
        self.path.write_text(text)
        with self.assertRaises(ValueError):load_sinr(self.path)

    def test_wrong_conversion_rejected(self):
        self.write([10])
        self.path.write_text(self.path.read_text().replace(',10,10.0,1,ok',',10,30.0,1,ok'))
        with self.assertRaises(ValueError):load_sinr(self.path)

    def test_schema_empty_and_malformed(self):
        self.path.write_text('time_s\n1\n')
        with self.assertRaises(ValueError):load_sinr(self.path)
        self.write([])
        with self.assertRaisesRegex(ValueError,'Empty'):load_sinr(self.path)
        self.write([1])
        self.path.write_text(self.path.read_text().replace(',1,0.0,1,ok',',bad,0.0,1,ok'))
        with self.assertRaises(ValueError):load_sinr(self.path)

    def test_time_order(self):
        self.write([1,2])
        lines=self.path.read_text().splitlines()
        self.path.write_text('\n'.join([lines[0],lines[2],lines[1]])+'\n')
        with self.assertRaisesRegex(ValueError,'Nonmonotonic'):load_sinr(self.path)

    def test_png_svg_and_point_counts(self):
        os.environ['MPLCONFIGDIR']=str(self.root/'cache')
        import matplotlib
        matplotlib.use('Agg')
        self.write([1,10,0])
        figures=render_sinr(load_sinr(self.path),self.root,[],1,lambda ax,events:None)
        self.assertEqual(figures['sinr_full']['DL_DATA'],2)
        self.assertEqual(len(list(self.root.glob('sinr_*.png'))),2)
        self.assertEqual(len(list(self.root.glob('sinr_*.svg'))),2)


if __name__=='__main__':unittest.main()
