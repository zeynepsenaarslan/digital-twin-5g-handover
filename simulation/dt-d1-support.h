/* Phase D1 research implementation; GPL-2.0-only (see standalone LICENSE).
 * Included after legacy loggers; keeps legacy execution and CSV schemas intact.
 */
#ifndef DT_D1_SUPPORT_H
#define DT_D1_SUPPORT_H
#include "ns3/flow-monitor-module.h"
#include <map>
#include <memory>
#include <set>

namespace d1
{
/**
 * Open a new CSV with a header, refusing an existing path.
 * @param out Output stream to initialize.
 * @param path Fresh CSV file path.
 * @param header Literal CSV column header.
 */
inline void Open(std::ofstream& out, const std::string& path, const char* header)
{
    NS_ABORT_MSG_IF(std::filesystem::exists(path), "Refuse existing D1 file: " << path);
    out.open(path);
    NS_ABORT_MSG_IF(!out, "Cannot open " << path);
    out << header << '\n' << std::fixed << std::setprecision(9);
}

/** Per-UE state; IMSI is stable, RNTI is read at each actual event. */
struct State
{
    uint32_t id{}; ///< Mobility UE index.
    Ptr<NrUeNetDevice> device; ///< Device supplying stable identity.
    Ipv4Address ip; ///< Unique destination IPv4 address.
    uint16_t port{}; ///< Per-UE destination UDP port.
    uint64_t tx{}, rx{}, bytes{}; ///< Application event counters.
    uint64_t starts{}, ends{}, errors{}, gnbEnds{}, attachments{}; ///< Actual RRC counters.
    uint64_t attempt{}; ///< Monotonic local attempt identifier.
    uint16_t source{}, target{}; ///< Active attempt cells.
    bool active{false}; ///< One active attempt for this UE only.
    std::map<std::pair<uint16_t,uint16_t>,std::pair<uint64_t,uint16_t>> pendingGnb; ///< (target cell,RNTI) to (attempt,source).
    std::set<uint32_t> received; ///< Unique packet sequences for this flow.
    std::ofstream* packets{}; ///< Shared, versioned packet event CSV.
    std::ofstream* events{}; ///< Shared, versioned handover event CSV.

    /**
     * Write observed UE event; never infer a transition from a target forecast.
     * @param event Native event label.
     * @param from Source cell identity.
     * @param to Target or current cell identity.
     * @param rnti Native event RNTI.
     * @param eventAttempt Explicit attempt identity, or sentinel to use the current attempt.
     */
    void Event(const char* event, uint16_t from, uint16_t to, uint16_t rnti,
               uint64_t eventAttempt = std::numeric_limits<uint64_t>::max())
    {
        *events << Simulator::Now().GetSeconds() << ',' << id << ',' << device->GetImsi()
                << ',' << (eventAttempt == std::numeric_limits<uint64_t>::max() ? attempt : eventAttempt) << ',' << event << ',' << from << ',' << to << ',' << rnti << '\n';
    }
    /**
     * Validate bound UE and observe initial/re-established RRC attachment.
     * @param imsi Stable IMSI from the trace.
     * @param cell Attached cell identity.
     * @param rnti Cell-local native RNTI.
     */
    void Attach(uint64_t imsi, uint16_t cell, uint16_t rnti)
    {
        NS_ABORT_MSG_IF(imsi != device->GetImsi(), "Attachment UE mismatch");
        ++attachments;
        Event("ConnectionEstablished", cell, cell, rnti);
    }
    /**
     * Begin one UE-local handover attempt.
     * @param imsi Stable IMSI from the trace.
     * @param cell Source cell identity.
     * @param rnti Source cell-local RNTI.
     * @param dest Proposed target cell identity.
     */
    void Start(uint64_t imsi, uint16_t cell, uint16_t rnti, uint16_t dest)
    {
        NS_ABORT_MSG_IF(imsi != device->GetImsi() || active, "Overlapping/misattributed handover");
        active = true; source = cell; target = dest; ++attempt; ++starts;
        Event("UE_HandoverStart", cell, dest, rnti);
    }
    /**
     * Observe actual successful UE completion.
     * @param imsi Stable IMSI from the trace.
     * @param cell Completed target cell identity.
     * @param rnti Target cell-local RNTI.
     */
    void End(uint64_t imsi, uint16_t cell, uint16_t rnti)
    {
        NS_ABORT_MSG_IF(imsi != device->GetImsi() || !active || cell != target,
                        "Unpaired UE handover completion");
        active = false; ++ends;
        NS_ABORT_MSG_IF(!pendingGnb.emplace(std::make_pair(cell,rnti),std::make_pair(attempt,source)).second,
                        "Duplicate pending gNB acknowledgement key");
        Event("UE_HandoverEndOk", source, cell, rnti);
    }
    /**
     * Observe actual UE error without assuming it is a standardized HFR outcome.
     * @param imsi Stable IMSI from the trace.
     * @param cell Cell identity reported on failure.
     * @param rnti Native failure RNTI.
     */
    void Error(uint64_t imsi, uint16_t cell, uint16_t rnti)
    {
        NS_ABORT_MSG_IF(imsi != device->GetImsi() || !active, "Unpaired handover error");
        active = false; ++errors;
        Event("UE_HandoverEndError", source, target, rnti);
    }
    /**
     * Log a successful application TX or actual RX with full flow identity.
     * @param event Successful TX or actual RX label.
     * @param seq Flow-local successful-send sequence.
     * @param sent Original packet creation time.
     * @param size Received or transmitted UDP datagram bytes.
     */
    void Packet(const char* event, uint32_t seq, Time sent, uint32_t size)
    {
        *packets << Simulator::Now().GetSeconds() << ',' << id << ',' << device->GetImsi()
                 << ',' << id << ',' << event << ',' << seq << ',' << sent.GetSeconds() << ','
                 << size << ',' << device->GetRrc()->GetCellId() << ','
                 << device->GetRrc()->GetRnti() << ",1\n";
    }
    /**
     * Parse the actual received SeqTsHeader and preserve duplicate evidence.
     * @param packet Actual received datagram including SeqTsHeader.
     */
    void Receive(Ptr<const ns3::Packet> packet)
    {
        SeqTsHeader header; packet->PeekHeader(header);
        ++rx; bytes += packet->GetSize(); received.insert(header.GetSeq());
        Packet("RX", header.GetSeq(), header.GetTs(), packet->GetSize());
    }
};

/** Dispatch shared gNB events by IMSI, never globally by RNTI. */
struct Dispatcher
{
    std::ofstream* measurements{}; ///< Quantized RRC reports, distinct from PHY values.
    std::map<uint64_t, State*> byImsi; ///< Registry of the three UE states.
    /**
     * Log actual gNB RRC report contents used by the native A3 policy.
     * @param imsi Stable IMSI from the gNB trace.
     * @param cell Reporting serving cell identity.
     * @param rnti Reporting cell-local RNTI.
     * @param report Native quantized RRC measurement report.
     */
    void Measurement(uint64_t imsi, uint16_t cell, uint16_t rnti,
                     NrRrcSap::MeasurementReport report)
    {
        NS_ABORT_MSG_IF(!byImsi.count(imsi), "Unknown RRC measurement IMSI");
        auto s = byImsi.at(imsi);
        for (const auto& neighbour : report.measResults.measResultListEutra)
        {
            if (!neighbour.haveRsrpResult) { continue; }
            *measurements << Simulator::Now().GetSeconds() << ',' << s->id << ',' << imsi
                          << ',' << cell << ',' << rnti << ',' << unsigned(report.measResults.measId)
                          << ',' << unsigned(report.measResults.measResultPCell.rsrpResult)
                          << ',' << neighbour.physCellId << ',' << unsigned(neighbour.rsrpResult) << '\n';
        }
    }
    /**
     * Associate a target completion with the latest UE-local attempt.
     * @param imsi Stable IMSI from the trace.
     * @param cell Completed target cell identity.
     * @param rnti Target cell-local RNTI.
     */
    void End(uint64_t imsi, uint16_t cell, uint16_t rnti)
    {
        NS_ABORT_MSG_IF(!byImsi.count(imsi), "Unknown gNB event IMSI");
        auto s = byImsi.at(imsi);
        auto pending=s->pendingGnb.find(std::make_pair(cell,rnti));
        NS_ABORT_MSG_IF(pending == s->pendingGnb.end(), "Unpaired gNB handover completion");
        ++s->gnbEnds;
        s->Event("gNB_HandoverEndOk", pending->second.second, cell, rnti, pending->second.first);
        s->pendingGnb.erase(pending);
    }
};

/** Low-rate UDP application; records only sends accepted by the socket. */
class Sender : public Application
{
  public:
    State* state{}; ///< Bound flow owner, alive until simulator destruction.
    Time end; ///< Exclusive sending deadline.
  private:
    Ptr<Socket> socket; ///< UDP source socket.
    EventId next; ///< Scheduled packet event.
    uint32_t sequence{}; ///< Successful-send sequence, local to this flow.
    /** Start the flow using an ephemeral source port. */
    void StartApplication() override
    {
        socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        NS_ABORT_MSG_IF(socket->Bind() < 0 || socket->Connect(
            InetSocketAddress(state->ip, state->port)) < 0, "D1 socket setup failed");
        Send();
    }
    /** Send the same 512-byte payload at the same 10 ms interval as legacy. */
    void Send()
    {
        if (Simulator::Now() >= end) { return; }
        NS_ABORT_MSG_IF(state->device->GetRrc()->GetState() != NrUeRrc::CONNECTED_NORMALLY &&
                        Simulator::Now() == Seconds(1), "Initial D1 attachment missing");
        SeqTsHeader header; header.SetSeq(sequence);
        auto packet = Create<Packet>(512 - header.GetSerializedSize()); packet->AddHeader(header);
        const auto sent = Simulator::Now();
        NS_ABORT_MSG_IF(socket->Send(packet) != 512, "D1 UDP send failed; no fabricated TX row");
        state->Packet("TX", sequence++, sent, 512); ++state->tx;
        next = Simulator::Schedule(MilliSeconds(10), &Sender::Send, this);
    }
    /** Cancel future sends and close the socket. */
    void StopApplication() override
    {
        Simulator::Cancel(next);
        if (socket) { socket->Close(); }
    }
};

/** Snapshot all UE positions, velocities and current RRC states at a fixed cadence. */
struct Sampler
{
    std::vector<std::unique_ptr<State>>* states{}; ///< Owned states in Run.
    NodeContainer nodes; ///< UE mobility nodes.
    Time stop, interval; ///< Inclusive observation bound and step.
    std::ofstream mobility, serving; ///< Versioned per-UE streams.
    /** Observe current state without updating radio or mobility. */
    void Sample()
    {
        auto now = Simulator::Now();
        for (const auto& s : *states)
        {
            auto mm = nodes.Get(s->id)->GetObject<MobilityModel>();
            auto p = mm->GetPosition(); auto v = mm->GetVelocity();
            mobility << now.GetSeconds() << ',' << s->id << ',' << s->device->GetImsi()
                     << ',' << p.x << ',' << p.y << ',' << p.z << ',' << v.x << ',' << v.y
                     << ',' << v.z << ',' << v.GetLength() << ",1\n";
            serving << now.GetSeconds() << ',' << s->id << ',' << s->device->GetImsi()
                    << ',' << s->device->GetRrc()->GetCellId() << ',' << s->device->GetRrc()->GetRnti()
                    << ',' << static_cast<int>(s->device->GetRrc()->GetState()) << ','
                    << (s->device->GetRrc()->GetState() == NrUeRrc::CONNECTED_NORMALLY) << '\n';
        }
        if (now + interval <= stop) { Simulator::Schedule(interval, &Sampler::Sample, this); }
    }
};

/**
 * Run deterministic D1, isolated from all default legacy execution paths.
 * @param duration Observation duration in seconds.
 * @param samplingMs Mobility and RRC sampling interval in milliseconds.
 * @param seed Explicit simulator seed.
 * @param run Explicit simulator run number.
 * @param handover Whether to enable unchanged A3-RSRP real-RRC X2 behavior.
 * @param output Fresh output directory.
 * @return Zero for validated simulation, nonzero for failed checks.
 */
inline int Run(double duration, uint32_t samplingMs, uint32_t seed, uint32_t run,
               bool handover, const std::string& output)
{
    NS_ABORT_MSG_IF(duration <= 2 || samplingMs == 0, "Invalid D1 time configuration");
    NS_ABORT_MSG_IF(std::filesystem::exists(output), "D1 requires a fresh output directory");
    std::filesystem::create_directories(output);
    RngSeedManager::SetSeed(seed); RngSeedManager::SetRun(run);
    NodeContainer gnbs, ues; gnbs.Create(2); ues.Create(3);
    auto gp = CreateObject<ListPositionAllocator>();
    gp->Add(Vector(0,0,25)); gp->Add(Vector(300,0,25));
    MobilityHelper gm; gm.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    gm.SetPositionAllocator(gp); gm.Install(gnbs);
    const std::vector<Vector> positions{{20,20,1.5},{280,-20,1.5},{25,60,1.5}};
    const std::vector<Vector> velocities{{5,0,0},{-5,0,0},{0,0,0}};
    auto up = CreateObject<ListPositionAllocator>(); for (auto p : positions) { up->Add(p); }
    MobilityHelper um; um.SetMobilityModel("ns3::ConstantVelocityMobilityModel");
    um.SetPositionAllocator(up); um.Install(ues);
    for (uint32_t i=0;i<3;++i) { ues.Get(i)->GetObject<ConstantVelocityMobilityModel>()->SetVelocity(velocities[i]); }
    auto epc = CreateObject<NrPointToPointEpcHelper>(); auto nr = CreateObject<NrHelper>();
    auto beam = CreateObject<IdealBeamformingHelper>();
    beam->SetAttribute("BeamformingMethod", TypeIdValue(DirectPathBeamforming::GetTypeId()));
    nr->SetEpcHelper(epc); nr->SetBeamformingHelper(beam);
    if (handover)
    {
        nr->SetAttribute("UseIdealRrc", BooleanValue(false));
        nr->SetHandoverAlgorithmType("ns3::NrA3RsrpHandoverAlgorithm");
        nr->SetHandoverAlgorithmAttribute("Hysteresis", DoubleValue(1.5));
        nr->SetHandoverAlgorithmAttribute("TimeToTrigger", TimeValue(MilliSeconds(128)));
    }
    auto [bandwidth,bwps] = nr->CreateBandwidthParts(
        {CcBwpCreator::SimpleOperationBandConf(3.5e9,20e6,1)}, "UMa");
    auto gd = nr->InstallGnbDevice(gnbs,bwps); auto ud = nr->InstallUeDevice(ues,bwps);
    for (uint32_t i=0;i<2;++i)
    {
        NrHelper::GetGnbPhy(gd.Get(i),0)->SetAttribute("Numerology",UintegerValue(1));
        NrHelper::GetGnbPhy(gd.Get(i),0)->SetTxPower(43);
        DynamicCast<NrGnbNetDevice>(gd.Get(i))->ConfigureCell();
    }
    if (handover) { nr->AddX2Interface(gnbs); }
    InternetStackHelper internet; internet.Install(ues); auto ips = epc->AssignUeIpv4Address(ud);
    auto [remote,remoteIp] = epc->SetupRemoteHost("100Mb/s",1500,MilliSeconds(1));
    std::ofstream registry, packets, events, summary, flows, cells, rrcReports, config;
    Open(config,output+"/run_config_v2.csv","scenario,duration_s,sampling_ms,seed,run,enable_handover,carrier_hz,bandwidth_hz,hysteresis_db,ttt_ms,traffic_interval_ms,udp_bytes");
    config << "d1," << duration << "," << samplingMs << "," << seed << "," << run << "," << handover << ",3500000000,20000000,1.5,128,10,512\n";
    Open(rrcReports,output+"/rrc_measurements_v2.csv","time_s,ue_id,imsi,serving_cell_id,rnti,meas_id,serving_rsrp_ie,neighbour_cell_id,neighbour_rsrp_ie");
    Open(registry,output+"/ue_registry_v2.csv","ue_id,imsi,node_id,ipv4,flow_id,destination_port,initial_cell_id,x0_m,y0_m,z0_m,vx_mps,vy_mps,vz_mps");
    Open(cells,output+"/cell_registry_v2.csv","gnb_id,node_id,cell_id,bwp_id,x_m,y_m,z_m");
    for (uint32_t i=0;i<2;++i) { cells << i << ',' << gnbs.Get(i)->GetId() << ',' << DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetCellId() << ",0," << i*300 << ",0,25\n"; }
    Open(packets,output+"/udp_packets_v2.csv","time_s,ue_id,imsi,flow_id,event,sequence,tx_time_s,udp_bytes,cell_id,rnti,valid");
    Open(events,output+"/handover_events_v2.csv","time_s,ue_id,imsi,attempt_id,event,source_cell_id,target_cell_id,rnti");
    Open(summary,output+"/udp_summary_v2.csv","ue_id,imsi,tx_packets,rx_packets,rx_unique,rx_bytes,lost_unique,final_cell_id,ho_starts,ho_ends,ho_errors,gnb_ends,active_attempt");
    Open(flows,output+"/flow_monitor_v2.csv","flow_monitor_id,ue_id,source_ip,destination_ip,source_port,destination_port,protocol,tx_packets,rx_packets,tx_ip_bytes,rx_ip_bytes,lost_packets,unresolved_packets");
    RadioMeasurementLogger radio(output+"/radio_measurements.csv");
    SinrMeasurementLogger sinr(output+"/sinr_measurements.csv");
    std::vector<std::unique_ptr<State>> states; Dispatcher dispatcher; dispatcher.measurements=&rrcReports;
    for (uint32_t i=0;i<3;++i)
    {
        auto s = std::make_unique<State>(); s->id=i; s->device=DynamicCast<NrUeNetDevice>(ud.Get(i));
        s->ip=ips.GetAddress(i); s->port=1234+i; s->packets=&packets; s->events=&events;
        dispatcher.byImsi.emplace(s->device->GetImsi(),s.get());
        auto rrc=s->device->GetRrc();
        NS_ABORT_MSG_IF(!rrc->TraceConnectWithoutContext("ConnectionEstablished",MakeCallback(&State::Attach,s.get())) ||
                        !rrc->TraceConnectWithoutContext("HandoverStart",MakeCallback(&State::Start,s.get())) ||
                        !rrc->TraceConnectWithoutContext("HandoverEndOk",MakeCallback(&State::End,s.get())) ||
                        !rrc->TraceConnectWithoutContext("HandoverEndError",MakeCallback(&State::Error,s.get())),"Missing UE traces");
        for (uint32_t bwp=0;bwp<bwps.size();++bwp)
        {
            auto phy=NrHelper::GetUePhy(s->device,bwp);
            NS_ABORT_MSG_IF(!phy->TraceConnectWithoutContext("ReportUeMeasurements",MakeCallback(&RadioMeasurementLogger::Record,&radio).Bind(s->device,i)) ||
                !phy->TraceConnectWithoutContext("DlDataSinr",MakeCallback(&SinrMeasurementLogger::Record,&sinr).Bind(s->device,i,std::string("DL_DATA"))) ||
                !phy->TraceConnectWithoutContext("DlCtrlSinr",MakeCallback(&SinrMeasurementLogger::Record,&sinr).Bind(s->device,i,std::string("DL_CONTROL"))),"Missing radio trace");
        }
        uint32_t initial=(i==1 ? 1 : 0);
        registry << i << ',' << s->device->GetImsi() << ',' << ues.Get(i)->GetId() << ',' << s->ip << ',' << i << ',' << s->port << ',' << DynamicCast<NrGnbNetDevice>(gd.Get(initial))->GetCellId()
                 << ',' << positions[i].x << ',' << positions[i].y << ',' << positions[i].z
                 << ',' << velocities[i].x << ',' << velocities[i].y << ',' << velocities[i].z << '\n';
        nr->AttachToGnb(ud.Get(i),gd.Get(initial));
        UdpServerHelper server(s->port); auto apps=server.Install(ues.Get(i));
        apps.Start(Seconds(0)); apps.Stop(Seconds(duration)+NanoSeconds(1));
        NS_ABORT_MSG_IF(!DynamicCast<UdpServer>(apps.Get(0))->TraceConnectWithoutContext("RxWithoutAddress",MakeCallback(&State::Receive,s.get())),"Missing RX trace");
        auto sender=CreateObject<Sender>(); sender->state=s.get(); sender->end=Seconds(duration-1);
        remote->AddApplication(sender); sender->SetStartTime(Seconds(1)); sender->SetStopTime(Seconds(duration-1));
        states.push_back(std::move(s));
    }
    for (uint32_t i=0;i<2;++i) { NS_ABORT_MSG_IF(!DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetRrc()->TraceConnectWithoutContext("HandoverEndOk",MakeCallback(&Dispatcher::End,&dispatcher)),"Missing gNB trace");
        NS_ABORT_MSG_IF(!DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetRrc()->TraceConnectWithoutContext("RecvMeasurementReport",MakeCallback(&Dispatcher::Measurement,&dispatcher)),"Missing RRC report trace"); }
    Sampler sampler; sampler.states=&states; sampler.nodes=ues; sampler.stop=Seconds(duration); sampler.interval=MilliSeconds(samplingMs);
    Open(sampler.mobility,output+"/ue_mobility_v2.csv","time_s,ue_id,imsi,x_m,y_m,z_m,vx_mps,vy_mps,vz_mps,speed_mps,valid");
    Open(sampler.serving,output+"/serving_cells_v2.csv","time_s,ue_id,imsi,cell_id,rnti,rrc_state,connected");
    Simulator::ScheduleNow(&Sampler::Sample,&sampler);
    FlowMonitorHelper fm; NodeContainer endpoints; endpoints.Add(remote); endpoints.Add(ues);
    auto monitor=fm.Install(endpoints);
    monitor->SetAttribute("DelayBinWidth",DoubleValue(0.001));
    monitor->SetAttribute("JitterBinWidth",DoubleValue(0.001));
    monitor->SetAttribute("PacketSizeBinWidth",DoubleValue(20));
    Simulator::Stop(Seconds(duration)+NanoSeconds(1)); Simulator::Run(); monitor->CheckForLostPackets();
    auto classifier=DynamicCast<Ipv4FlowClassifier>(fm.GetClassifier());
    std::vector<uint64_t> ipTx(3),ipRx(3); std::set<uint32_t> mapped;
    for (const auto& [fid,stats] : monitor->GetFlowStats())
    {
        auto tuple=classifier->FindFlow(fid);
        if (tuple.protocol!=17) { continue; }
        State* owner=nullptr;
        for (const auto& s:states) { if (tuple.destinationAddress==s->ip && tuple.destinationPort==s->port && tuple.sourceAddress==remoteIp) { owner=s.get(); } }
        NS_ABORT_MSG_IF(!owner,"Unmapped UDP FlowMonitor flow");
        auto i=owner->id; mapped.insert(i); ipTx[i]+=stats.txPackets; ipRx[i]+=stats.rxPackets;
        NS_ABORT_MSG_IF(stats.txPackets < stats.rxPackets+stats.lostPackets,"FlowMonitor counter inconsistency");
        flows << fid << ',' << i << ',' << tuple.sourceAddress << ',' << tuple.destinationAddress << ',' << tuple.sourcePort << ',' << tuple.destinationPort << ',' << unsigned(tuple.protocol)
              << ',' << stats.txPackets << ',' << stats.rxPackets << ',' << stats.txBytes << ',' << stats.rxBytes << ',' << stats.lostPackets << ',' << stats.txPackets-stats.rxPackets-stats.lostPackets << '\n';
    }
    bool ok=mapped.size()==3;
    for (const auto& s:states)
    {
        summary << s->id << ',' << s->device->GetImsi() << ',' << s->tx << ',' << s->rx << ',' << s->received.size() << ',' << s->bytes << ',' << s->tx-s->received.size() << ',' << s->device->GetRrc()->GetCellId()
                << ',' << s->starts << ',' << s->ends << ',' << s->errors << ',' << s->gnbEnds << ',' << s->active << '\n';
        ok = ok && s->attachments==1 && s->tx>0 && s->rx>0 && s->rx==s->received.size() && s->bytes==s->rx*512 &&
             ipTx[s->id]==s->tx && ipRx[s->id]==s->rx && !s->active && s->pendingGnb.empty() && !s->errors && s->starts==s->ends && s->ends==s->gnbEnds &&
             s->device->GetRrc()->GetState()==NrUeRrc::CONNECTED_NORMALLY;
        std::cout << "D1 UE=" << s->id << " IMSI=" << s->device->GetImsi() << " IP=" << s->ip << " TX=" << s->tx << " RX=" << s->rx << " HO=" << s->ends << " final_cell=" << s->device->GetRrc()->GetCellId() << '\n';
    }
    radio.Close(); sinr.Close();
    for (auto* stream : {&registry,&packets,&events,&summary,&flows,&cells,&sampler.mobility,&sampler.serving,&rrcReports,&config}) { stream->close(); NS_ABORT_MSG_IF(stream->fail(),"D1 CSV write failure"); }
    Simulator::Destroy();
    std::cout << "PHASE D1 SIMULATION: " << (ok ? "PASS" : "FAIL") << std::endl;
    return ok ? 0 : 1;
}
} // namespace d1
#endif
