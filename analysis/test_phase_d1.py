"""Meaningful cross-UE corruption tests for D1 joins (GPL-2.0-only)."""
import copy
import unittest
from phase_d1 import identity, packet_accounting, handovers, ns


class D1IdentityTests(unittest.TestCase):
    def setUp(self):
        self.reg={str(i):dict(ue_id=str(i),imsi=str(2+i),flow_id=str(i),initial_cell_id='1' if i==0 else '2') for i in range(2)}
        self.packets=[];self.summary={}
        for u,r in self.reg.items():
            for event,time in [('TX','1.000000000'),('RX','1.003000000')]:
                self.packets.append(dict(ue_id=u,imsi=r['imsi'],flow_id=u,event=event,time_s=time,tx_time_s='1.000000000',sequence='0',udp_bytes='512',valid='1'))
            self.summary[u]=dict(tx_packets='1',rx_packets='1',rx_bytes='512',rx_unique='1',lost_unique='0')

    def test_same_sequence_and_rnti_are_not_global_identity(self):
        result=packet_accounting(self.packets,self.reg,self.summary)
        self.assertEqual({u:len(v) for u,v in result.items()},{'0':1,'1':1})

    def test_cross_ue_imsi_rejected(self):
        self.packets[-1]['imsi']='2'
        with self.assertRaisesRegex(ValueError,'UE/IMSI'):packet_accounting(self.packets,self.reg,self.summary)

    def test_cross_flow_rejected(self):
        self.packets[-1]['flow_id']='0'
        with self.assertRaisesRegex(ValueError,'flow'):packet_accounting(self.packets,self.reg,self.summary)

    def test_wrong_tx_timestamp_rejected(self):
        self.packets[-1]['tx_time_s']='1.001000000'
        with self.assertRaisesRegex(ValueError,'matching successful TX'):packet_accounting(self.packets,self.reg,self.summary)

    def test_duplicate_callback_rejected(self):
        self.packets.append(copy.deepcopy(self.packets[-1]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):packet_accounting(self.packets,self.reg,self.summary)

    def test_aggregate_mismatch_rejected(self):
        self.summary['1']['rx_bytes']='1024'
        with self.assertRaisesRegex(ValueError,'counter'):packet_accounting(self.packets,self.reg,self.summary)

    def test_timestamp_nan_rejected(self):
        with self.assertRaises(ValueError):ns('NaN')

    def events(self):
        result=[]
        for u,r in self.reg.items():
            source=r['initial_cell_id'];target='2' if source=='1' else '1'
            for event,t,a in [('ConnectionEstablished','.02','0'),('UE_HandoverStart','20','1'),('UE_HandoverEndOk','20.002','1'),('gNB_HandoverEndOk','20.006','1')]:
                result.append(dict(ue_id=u,imsi=r['imsi'],event=event,time_s=t,attempt_id=a,source_cell_id=source,target_cell_id=source if a=='0' else target,rnti='1'))
        return result

    def test_simultaneous_handover_local_attempts(self):
        result=handovers(self.events(),self.reg)
        self.assertEqual(result['0'][0]['target'],'2');self.assertEqual(result['1'][0]['target'],'1')

    def test_cross_target_completion_rejected(self):
        events=self.events();events[2]['target_cell_id']='1'
        with self.assertRaisesRegex(ValueError,'Unpaired/misattributed'):handovers(events,self.reg)

    def test_missing_terminal_rejected(self):
        events=self.events();events=[e for e in events if not (e['ue_id']=='1' and 'End' in e['event'])]
        with self.assertRaisesRegex(ValueError,'Incomplete'):handovers(events,self.reg)

    def test_delayed_gnb_ack_keeps_original_attempt(self):
        events=self.events()
        old_ack=copy.deepcopy(events[3]);old_ack['time_s']='20.005'
        start=copy.deepcopy(events[1]);start.update(time_s='20.004',attempt_id='2',source_cell_id='2',target_cell_id='1',rnti='2')
        end=copy.deepcopy(start);end.update(time_s='20.006',event='UE_HandoverEndOk')
        ack=copy.deepcopy(end);ack.update(time_s='20.010',event='gNB_HandoverEndOk')
        result=handovers(events[:3]+[start,old_ack,end,ack]+events[4:],self.reg)
        self.assertEqual(len(result['0']),2)
        self.assertEqual(result['0'][1]['target'],'1')

    def test_repeated_gnb_callback_rejected(self):
        events=self.events();events.append(copy.deepcopy(events[-1]))
        with self.assertRaisesRegex(ValueError,'Unpaired gNB'):handovers(events,self.reg)


if __name__=='__main__':unittest.main()
