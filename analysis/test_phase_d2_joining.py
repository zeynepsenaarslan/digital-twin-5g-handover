"""Joining proof and power-profile corruption tests; GPL-2.0-only."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from phase_d2 import radio_profile
from phase_d2_joining import summarize


class JoiningProofTests(unittest.TestCase):
    def setUp(self):
        self.rows=[]
        def add(t,layer,event,detail='',imsi='4',rnti='5'):
            self.rows.append(dict(sequence=str(len(self.rows)),time_ns=str(t),layer=layer,event=event,
                                  imsi=imsi,cell_id='2',rnti=rnti,detail=detail))
        add(100,'gNB_RRC','CONTEXT_CREATED','state=8',imsi='0')
        add(100,'gNB_RRC','AFTER_CREATE','present=1;state=8')
        add(105,'UE_PDCP','TX','lcid=1;bytes=3')
        add(106,'UE_PHY','UL_TX','duration_ns=2;dbm=2')
        add(107,'UE_RLC','TX','lcid=1;bytes=7')
        add(110,'gNB_PHY','SNR','linear=0.01',imsi='0',rnti='0')
        add(110,'gNB_PHY','UL_TB','sinr=0.01;rb=53;corrupt=1;tbler=1')
        add(110,'gNB_PHY','UL_TB','sinr=0.01;rb=53;corrupt=1;tbler=1')
        add(200000100,'gNB_RRC','JOIN_TIMEOUT_FIRED','present=1;state=8')
        add(200000100,'gNB_RRC','RELEASE_BEFORE_ERASE','present=1;state=8')
        add(200000100,'gNB_RRC','AFTER_ERASE','present=0',imsi='0')

    def test_context_exists_then_is_erased(self):
        r=summarize(self.rows)
        self.assertTrue(r['context_present_during_failure'])
        self.assertEqual(r['unique_transport_blocks'],1)
        self.assertEqual(r['native_tb_trace_rows'],2)
        self.assertFalse(r['hypothesis_context_absent_before_timeout'])

    def test_absent_context_claim_rejected(self):
        self.rows[-3]['detail']='present=0'
        with self.assertRaisesRegex(ValueError,'presence'):summarize(self.rows)

    def test_interference_must_not_be_called_noise(self):
        self.rows[5]['detail']='linear=1.0'
        with self.assertRaisesRegex(ValueError,'Noise-limited'):summarize(self.rows)

    def test_partial_rb_snr_not_falsely_compared(self):
        self.rows[6]['detail']=self.rows[6]['detail'].replace('rb=53','rb=1')
        with self.assertRaisesRegex(ValueError,'53 RBs'):summarize(self.rows)

    def test_changed_watchdog_cannot_claim_same_fix(self):
        for r in self.rows[-3:]:r['time_ns']='300000100'
        with self.assertRaisesRegex(ValueError,'200 ms'):summarize(self.rows)

    def test_out_of_order_deletion_rejected(self):
        self.rows[-1]['sequence']='0'
        with self.assertRaisesRegex(ValueError,'order'):summarize(self.rows)

    def test_historical_profile_is_inherited_two(self):
        with tempfile.TemporaryDirectory() as d:
            r=radio_profile(Path(d));self.assertEqual(r['ue_tx_power_dbm'],2);self.assertEqual(r['origin'],'library_default')

    def test_explicit_profile_and_probe_guard(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);p=path/'radio_profile.json'
            p.write_text(json.dumps(dict(ue_tx_power_dbm=23,uplink_power_control=False,joining_power_probe=False)))
            self.assertEqual(radio_profile(path)['origin'],'explicit')
            p.write_text(json.dumps(dict(ue_tx_power_dbm=23,uplink_power_control=False,joining_power_probe=True)))
            with self.assertRaisesRegex(ValueError,'2 dBm baseline'):radio_profile(path)


if __name__=='__main__':unittest.main()
