"""D2 corruption and boundary tests; GPL-2.0-only."""
import copy
import csv
from pathlib import Path
import tempfile
import unittest

from phase_d2 import (candidate_rows, ingress_qos, trajectory, validate_slots,
                      rows, handovers, ns, link_failures)


class D2Contracts(unittest.TestCase):
    def setUp(self):
        self.registry={str(i):dict(ue_id=str(i),imsi=str(10+i),flow_id=str(i),initial_cell_id='1') for i in range(5)}
        self.cells={str(i):dict(bwp_id='0') for i in range(1,4)}
        self.radio=[]
        for u,r in self.registry.items():
            for c in self.cells:
                self.radio.append(dict(time_s='.2',ue_id=u,imsi=r['imsi'],flow_id=u,bwp_id='0',
                                       serving_cell_id='1',measured_cell_id=c,metric='rsrp',value=str(-60-int(c))))
        self.slots=[]
        for c in self.cells:
            for i in range(3):
                self.slots.append(dict(time_s=f'{i/2000:.9f}',slot_index=str(i),cell_id=c,bwp_id='0',
                                       active_rntis='1',allocated_prb_symbols='12' if i!=1 else '0',
                                       data_symbols='2' if i!=1 else '0',available_prbs='10',available_symbols='12',
                                       full_slot_symbols='14',source='NrGnbPhy::SlotDataStats'))

    def test_two_real_neighbours_ranked(self):
        result,coverage=candidate_rows(self.radio,self.registry,self.cells)
        self.assertEqual(len(result),10)
        self.assertEqual(set(coverage.values()),{1})
        self.assertEqual([r['rank'] for r in result[:2]],[1,2])

    def test_missing_candidate_not_fabricated(self):
        extra=copy.deepcopy(self.radio[0]);extra['time_s']='.4'
        result,_=candidate_rows(self.radio+[extra],self.registry,self.cells)
        missing=[r for r in result if r['time_s']=='.4']
        self.assertEqual(len(missing),2)
        self.assertTrue(all((r['measured'],r['rsrp_dbm'],r['rank'])==(0,'','') for r in missing))

    def test_no_multi_candidate_evidence_fails(self):
        with self.assertRaisesRegex(ValueError,'two-neighbour'):
            candidate_rows([r for r in self.radio if r['measured_cell_id']!='3'],self.registry,self.cells)

    def test_duplicate_candidate_fails(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            candidate_rows(self.radio+[self.radio[0]],self.registry,self.cells)

    def test_cross_ue_candidate_fails(self):
        self.radio[0]['imsi']='11'
        with self.assertRaisesRegex(ValueError,'UE/IMSI'):candidate_rows(self.radio,self.registry,self.cells)

    def test_exact_turn_and_stop(self):
        reg=dict(x0_m='20',y0_m='0',z0_m='1.5',vx_mps='5',vy_mps='0',vz_mps='0')
        self.assertEqual(trajectory(reg,40,40),([220,0,1.5],[-5,0,0]))
        self.assertEqual(trajectory(reg,80,40),([20,0,1.5],[0,0,0]))
        self.assertEqual(trajectory(reg,90,40),([20,0,1.5],[0,0,0]))
        self.assertAlmostEqual(trajectory(reg,79.999,40)[0][0],20.005)

    def test_native_prb_totals_and_idle(self):
        totals,bins=validate_slots(self.slots,self.cells,1_000_000)
        self.assertEqual(totals['1']['allocated_prb_symbols'],24)
        self.assertEqual(totals['1']['available_prb_symbols'],360)
        self.assertEqual(totals['1']['idle_slots'],1)
        self.assertEqual(bins[(0,'1')],[12,240,2])

    def test_bootstrap_gap_is_visible_not_zero_filled(self):
        records=copy.deepcopy([r for r in self.slots if r['slot_index']!='1'])
        for r in records:
            if r['slot_index']=='0':r.update(allocated_prb_symbols='0',data_symbols='0')
        totals,bins=validate_slots(records,self.cells,1_000_000,allow_bootstrap_gap=True)
        self.assertEqual(totals['1']['missing_slot_indices'],[1])
        self.assertEqual(totals['1']['slots'],2)
        self.assertEqual(bins[(0,'1')],[0,120,1])

    def test_bootstrap_allowance_does_not_hide_later_gap(self):
        records=[r for r in self.slots if r['slot_index']!='2']
        with self.assertRaisesRegex(ValueError,'coverage'):
            validate_slots(records,self.cells,1_000_000,allow_bootstrap_gap=True)

    def test_missing_slot_fails(self):
        with self.assertRaisesRegex(ValueError,'gap|coverage'):
            validate_slots(self.slots[1:],self.cells,1_000_000)

    def test_duplicate_slot_fails(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            validate_slots(self.slots+[self.slots[-1]],self.cells,1_000_000)

    def test_prb_overallocation_fails(self):
        self.slots[0]['allocated_prb_symbols']='121'
        with self.assertRaisesRegex(ValueError,'overflow'):validate_slots(self.slots,self.cells,1_000_000)

    def test_estimated_load_cannot_claim_native(self):
        self.slots[0]['source']='attached_ues_estimate'
        with self.assertRaisesRegex(ValueError,'native'):validate_slots(self.slots,self.cells,1_000_000)

    def packet_fixture(self):
        base=dict(ue_id='0',imsi='10',flow_id='0',sequence='0',tx_time_s='1.000000000',udp_bytes='512',valid='1')
        packets=[dict(base,event='TX',time_s='1.000000000',cell_id='1'),
                 dict(base,event='RX',time_s='1.100000000',cell_id='2')]
        ingress=[dict(base,time_s='1.002000000',cell_id='1',source='NrEpcGnbApplication::RxFromS1u')]
        return packets,ingress

    def test_ingress_cohort_preserved_across_handover(self):
        packets,ingress=self.packet_fixture()
        totals,_,derived=ingress_qos(ingress,packets,self.registry,self.cells,2_000_000_000)
        self.assertEqual(totals['1']['rx_bytes'],512)
        self.assertEqual(totals['2']['rx_bytes'],0)
        self.assertEqual(derived[0]['ingress_cell_id'],'1')
        self.assertEqual(derived[0]['rx_rrc_cell_id'],'2')
        self.assertAlmostEqual(derived[0]['delay_ms'],100)

    def test_duplicate_ingress_fails(self):
        packets,ingress=self.packet_fixture()
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            ingress_qos(ingress+ingress,packets,self.registry,self.cells,2_000_000_000)

    def test_unobserved_ingress_not_assigned_from_rrc(self):
        packets,_=self.packet_fixture()
        with self.assertRaisesRegex(ValueError,'lacks actual cell ingress'):
            ingress_qos([],packets,self.registry,self.cells,2_000_000_000)

    def test_diagnostic_missing_ingress_has_no_invented_cell(self):
        packets,_=self.packet_fixture()
        totals,_,_=ingress_qos([],packets[:1],self.registry,self.cells,2_000_000_000,allow_unattributed=True)
        self.assertEqual(totals['_unattributed'][0]['reason'],'no_observed_S1U_ingress')
        self.assertNotIn('cell_id',totals['_unattributed'][0])
        self.assertTrue(all(totals[c]['ingress_packets']==0 for c in self.cells))

    def test_wrong_ingress_sequence_fails(self):
        packets,ingress=self.packet_fixture();ingress[0]['sequence']='1'
        with self.assertRaises(ValueError):ingress_qos(ingress,packets,self.registry,self.cells,2_000_000_000)

    def test_undelivered_is_cohort_accounted(self):
        packets,ingress=self.packet_fixture()
        totals,_,_=ingress_qos(ingress,packets[:1],self.registry,self.cells,2_000_000_000)
        self.assertEqual(totals['1']['undelivered'],1)
        self.assertEqual(totals['1']['delivery_fraction'],0)
        self.assertIsNone(totals['1']['mean_received_delay_ms'])

    def test_schema_extra_column_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'x2_registry_v3.csv').write_text('source_cell_id,target_cell_id,unexpected\n1,2,3\n')
            with self.assertRaisesRegex(ValueError,'schema'):list(rows(p,'x2_registry_v3.csv'))

    def test_schema_empty_optional_event_file(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'x2_registry_v3.csv').write_text('source_cell_id,target_cell_id\n')
            self.assertEqual(list(rows(p,'x2_registry_v3.csv')),[])

    def event_fixture(self):
        events=[]
        for u,r in self.registry.items():
            for event,t,a in [('ConnectionEstablished','.02','0'),('UE_HandoverStart','2','1'),('UE_HandoverEndOk','2.002','1'),('gNB_HandoverEndOk','2.006','1')]:
                events.append(dict(ue_id=u,imsi=r['imsi'],event=event,time_s=t,attempt_id=a,
                                   source_cell_id='1',target_cell_id='1' if a=='0' else '2',rnti='1'))
        return events

    def test_five_simultaneous_cell_local_rntis(self):
        result=handovers(self.event_fixture(),self.registry)
        self.assertEqual(sum(map(len,result.values())),5)

    def test_cross_target_terminal_rejected(self):
        events=self.event_fixture();events[2]['target_cell_id']='3'
        with self.assertRaisesRegex(ValueError,'Unpaired'):handovers(events,self.registry)

    def test_missing_terminal_rejected(self):
        with self.assertRaisesRegex(ValueError,'Incomplete'):handovers(self.event_fixture()[:-2],self.registry)

    def test_pending_gnb_ack_is_not_success_in_diagnostic_mode(self):
        events=self.event_fixture();events.pop()
        result=handovers(events,self.registry,require_gnb_completion=False)
        self.assertTrue(result['4'][0]['ue_end_ok'])
        self.assertFalse(result['4'][0]['gnb_completed'])
        self.assertFalse(result['4'][0]['success'])
        with self.assertRaisesRegex(ValueError,'incomplete'):handovers(events,self.registry)

    def test_joining_failure_links_target_cell_and_rnti(self):
        events=self.event_fixture();events.pop()
        intervals=handovers(events,self.registry,require_gnb_completion=False)
        failures=[dict(ue_id='4',time_s='2.2',event='HandoverFailureJoining',cell_id='2',rnti='1')]
        link_failures(failures,intervals)
        self.assertEqual(failures[0]['attempt_id'],1)
        failures[0]['cell_id']='3'
        with self.assertRaisesRegex(ValueError,'cell/RNTI'):link_failures(failures,intervals)

    def test_duplicate_gnb_ack_rejected(self):
        events=self.event_fixture()
        with self.assertRaisesRegex(ValueError,'Unpaired gNB'):handovers(events+[events[-1]],self.registry)

    def test_handover_before_attachment_rejected(self):
        events=self.event_fixture();events.pop(0)
        with self.assertRaisesRegex(ValueError,'before initial'):handovers(events,self.registry)

    def test_nan_or_sub_nanosecond_time_fails(self):
        for value in ('NaN','-1','0.0000000001'):
            with self.assertRaises(ValueError):ns(value)


if __name__=='__main__':unittest.main()
