/* Phase D2 research implementation; GPL-2.0-only (see standalone LICENSE).
 * Included after legacy loggers; keeps legacy execution and CSV schemas intact.
 */
#ifndef DT_D2_SUPPORT_H
#define DT_D2_SUPPORT_H
#include "ns3/flow-monitor-module.h"
#include <map>
#include <memory>
#include <set>

namespace d2
{
/**
 * Open a new CSV with a header, refusing an existing path.
 * @param out Output stream to initialize.
 * @param path Fresh CSV file path.
 * @param header Literal CSV column header.
 */
inline void Open(std::ofstream& out, const std::string& path, const char* header)
{
    NS_ABORT_MSG_IF(std::filesystem::exists(path), "Refuse existing D2 file: " << path);
    out.open(path);
    NS_ABORT_MSG_IF(!out, "Cannot open " << path);
    out << header << '\n' << std::fixed << std::setprecision(9);
}

/**
 * Record an effective object attribute without changing simulator state.
 * @param out Fresh settings stream.
 * @param scope Object role (UE, gNB, channel or array).
 * @param id Registry identity in that scope.
 * @param object Inspected object.
 * @param attribute Gettable attribute name.
 * @param origin Explicit scenario setting or inherited library default.
 */
inline void Setting(std::ofstream& out, const std::string& scope, uint32_t id,
                    Ptr<Object> object, const std::string& attribute, const std::string& origin)
{
    StringValue value; object->GetAttribute(attribute,value);
    NS_ABORT_MSG_IF(value.Get().find_first_of(",\n")!=std::string::npos,"Non-scalar setting");
    out << scope << ',' << id << ',' << object->GetInstanceTypeId().GetName() << ','
        << attribute << ',' << value.Get() << ',' << origin << '\n';
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
        std::cout << "D2 event UE=" << id << " IMSI=" << device->GetImsi() << " event=" << event
                  << " time=" << Simulator::Now().GetSeconds() << " source=" << from << " target=" << to << std::endl;
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
    std::map<uint64_t, State*> byImsi; ///< Registry of all five UE states.
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
            InetSocketAddress(state->ip, state->port)) < 0, "D2 socket setup failed");
        Send();
    }
    /** Send the same 512-byte payload at the same 10 ms interval as legacy. */
    void Send()
    {
        if (Simulator::Now() >= end) { return; }
        NS_ABORT_MSG_IF(state->attachments != 1 && Simulator::Now() == Seconds(1), "Initial D2 attachment missing: UE=" << state->id << " RRC=" << state->device->GetRrc()->GetState() << " attachments=" << state->attachments);
        SeqTsHeader header; header.SetSeq(sequence);
        auto packet = Create<Packet>(512 - header.GetSerializedSize()); packet->AddHeader(header);
        const auto sent = Simulator::Now();
        NS_ABORT_MSG_IF(socket->Send(packet) != 512, "D2 UDP send failed; no fabricated TX row");
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

/** Passive native infrastructure traces. No packet or simulator state mutation. */
struct Infrastructure
{
    std::ofstream slots; ///< Native DATA/MSG3 allocation evidence, both directions.
    std::ofstream ingress; ///< Actual accepted S1-U inner datagrams.
    std::ofstream failures; ///< Native gNB handover failure notifications.
    std::map<uint64_t,uint32_t> byImsi; ///< Global UE identity registry for diagnostics.
    /**
     * Preserve native failure evidence without inventing an attempt association.
     * @param event Bound native failure trace name.
     * @param imsi Native UE IMSI.
     * @param rnti Native cell-local RNTI.
     * @param cell Native reporting cell.
     */
    void Failure(std::string event, uint64_t imsi, uint16_t rnti, uint16_t cell)
    {
        NS_ABORT_MSG_IF(!byImsi.count(imsi),"Unknown failure IMSI");
        failures << Simulator::Now().GetSeconds() << ',' << byImsi.at(imsi) << ',' << imsi
                 << ',' << cell << ',' << rnti << ',' << event << '\n';
        std::cout << "D2 native " << event << " IMSI=" << imsi << " cell=" << cell
                  << " RNTI=" << rnti << " time=" << Simulator::Now().GetSeconds() << std::endl;
    }
    std::map<std::pair<Ipv4Address,uint16_t>,std::pair<uint32_t,uint64_t>> byDestination; ///< IP/port to UE/IMSI.
    /**
     * Log native per-slot counters in their actual PRB-symbol units.
     * @param phy Bound PHY for full-slot symbol denominator.
     * @param slot Native slot identity.
     * @param active Distinct nonzero allocated RNTIs, not attached population.
     * @param used DATA and MSG3 allocated PRB-symbols.
     * @param symbols Native used data symbol count.
     * @param rb Available PRBs.
     * @param available Available symbols excluding control.
     * @param bwp Native BWP ID.
     * @param cell Native cell ID.
     */
    void Slot(Ptr<NrGnbPhy> phy, const SfnSf& slot, uint32_t active, uint32_t used,
              uint32_t symbols, uint32_t rb, uint32_t available, uint16_t bwp, uint16_t cell)
    {
        slots << Simulator::Now().GetSeconds() << ',' << slot.Normalize() << ',' << cell << ',' << bwp
              << ',' << active << ',' << used << ',' << symbols << ',' << rb << ',' << available
              << ',' << phy->GetSymbolsPerSlot() << ",NrGnbPhy::SlotDataStats\n";
    }
    /**
     * Decode an actual accepted S1-U packet on a copy.
     * @param cell Bound ingress gNB cell identity.
     * @param packet Inner IP datagram provided by native trace after GTP removal.
     */
    void Ingress(uint16_t cell, Ptr<ns3::Packet> packet)
    {
        auto copy=packet->Copy(); Ipv4Header ip; UdpHeader udp; SeqTsHeader seq;
        NS_ABORT_MSG_IF(!copy->RemoveHeader(ip) || ip.GetProtocol()!=17 ||
                        !copy->RemoveHeader(udp),"Unexpected D2 ingress protocol");
        auto key=std::make_pair(ip.GetDestination(),udp.GetDestinationPort());
        NS_ABORT_MSG_IF(!byDestination.count(key),"Unknown D2 ingress flow");
        auto [ue,imsi]=byDestination.at(key);
        const auto size=copy->GetSize();
        NS_ABORT_MSG_IF(size!=512 || !copy->RemoveHeader(seq),"Invalid D2 ingress payload");
        ingress << Simulator::Now().GetSeconds() << ',' << cell << ',' << ue << ',' << imsi << ','
                << ue << ',' << seq.GetSeq() << ',' << seq.GetTs().GetSeconds() << ',' << size
                << ",NrEpcGnbApplication::RxFromS1u\n";
    }
};

/**
 * Run deterministic D2, isolated from all default legacy execution paths.
 * @param duration Observation duration in seconds.
 * @param samplingMs Mobility and RRC sampling interval in milliseconds.
 * @param seed Explicit simulator seed.
 * @param run Explicit simulator run number.
 * @param handover Whether to enable unchanged A3-RSRP real-RRC X2 behavior.
 * @param turn Outbound duration before reversal; stop at twice this time.
 * @param output Fresh output directory.
 * @return Zero for validated simulation, nonzero for failed checks.
 */
inline int Run(double duration, uint32_t samplingMs, uint32_t seed, uint32_t run,
               bool handover, double turn, const std::string& output)
{
    NS_ABORT_MSG_IF(!std::isfinite(duration) || !std::isfinite(turn) || turn <= 1 || 2*turn >= duration-1 || samplingMs == 0, "Invalid D2 time configuration");
    NS_ABORT_MSG_IF(std::filesystem::exists(output), "D2 requires a fresh output directory");
    std::filesystem::create_directories(output);
    RngSeedManager::SetSeed(seed); RngSeedManager::SetRun(run);
    NodeContainer gnbs, ues; gnbs.Create(3); ues.Create(5);
    auto gp = CreateObject<ListPositionAllocator>();
    const std::vector<Vector> sites{{0,0,25},{300,0,25},{150,259.807621135,25}};
    for (auto p : sites) { gp->Add(p); }
    MobilityHelper gm; gm.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    gm.SetPositionAllocator(gp); gm.Install(gnbs);
    const std::vector<Vector> positions{{20,20,1.5},{280,20,1.5},{150,239.807621135,1.5},{150,180,1.5},{25,60,1.5}};
    const std::vector<Vector> velocities{{5,0,0},{-2.5,4.330127018922193,0},{-2.5,-4.330127018922193,0},{0,0,0},{0,0,0}};
    auto up = CreateObject<ListPositionAllocator>(); for (auto p : positions) { up->Add(p); }
    MobilityHelper um; um.SetMobilityModel("ns3::ConstantVelocityMobilityModel");
    um.SetPositionAllocator(up); um.Install(ues);
    for (uint32_t i=0;i<5;++i)
    {
        auto mobility = ues.Get(i)->GetObject<ConstantVelocityMobilityModel>();
        mobility->SetVelocity(velocities[i]);
        Simulator::Schedule(Seconds(turn), &ConstantVelocityMobilityModel::SetVelocity,
                            mobility, Vector(-velocities[i].x,-velocities[i].y,0));
        Simulator::Schedule(Seconds(2*turn), &ConstantVelocityMobilityModel::SetVelocity,
                            mobility, Vector(0,0,0));
    }
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
    for (uint32_t i=0;i<3;++i)
    {
        NrHelper::GetGnbPhy(gd.Get(i),0)->SetAttribute("Numerology",UintegerValue(1));
        NrHelper::GetGnbPhy(gd.Get(i),0)->SetTxPower(43);
        DynamicCast<NrGnbNetDevice>(gd.Get(i))->ConfigureCell();
    }
    if (handover) { nr->AddX2Interface(gnbs); }
    InternetStackHelper internet; internet.Install(ues); auto ips = epc->AssignUeIpv4Address(ud);
    auto [remote,remoteIp] = epc->SetupRemoteHost("100Mb/s",1500,MilliSeconds(1));
    NrHelper::StreamAssignmentParams streams;
    streams.assignEpc=true; streams.remoteHostNodes.Add(remote);
    streams.ueNodes=ues; streams.gnbNodes=gnbs; streams.beamformingHelper=beam;
    streams.gnbDevs=gd; streams.ueDevs=ud;
    const auto assignedStreams=nr->AssignStreams(streams);
    std::cout << "D2 assigned RNG streams=" << assignedStreams << '\n';
    std::ofstream registry, packets, events, summary, flows, cells, rrcReports, config, x2, traces, settings, contexts;
    Open(contexts,output+"/gnb_context_v3.csv","time_s,ue_id,imsi,cell_id,rnti,ue_rrc_state,gnb_context_present,gnb_imsi,gnb_rrc_state,pending_gnb_completions");
    Open(settings,output+"/radio_settings_v3.csv","scope,id,object_type,attribute,value,origin");
    Open(x2,output+"/x2_registry_v3.csv","source_cell_id,target_cell_id");
    for (uint32_t i=0;i<3;++i) { for (uint32_t j=i+1;j<3;++j) {
        x2 << DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetCellId() << ','
           << DynamicCast<NrGnbNetDevice>(gd.Get(j))->GetCellId() << '\n'; } }
    Open(traces,output+"/trace_registry_v3.csv","scope,node_id,ue_id,imsi,cell_id,bwp_id,trace,source");
    Infrastructure infrastructure;
    Open(infrastructure.failures,output+"/gnb_failures_v3.csv","time_s,ue_id,imsi,cell_id,rnti,event");
    Open(infrastructure.slots,output+"/prb_slots_v3.csv","time_s,slot_index,cell_id,bwp_id,active_rntis,allocated_prb_symbols,data_symbols,available_prbs,available_symbols,full_slot_symbols,source");
    Open(infrastructure.ingress,output+"/cell_ingress_v3.csv","time_s,cell_id,ue_id,imsi,flow_id,sequence,tx_time_s,udp_bytes,source");
    for (uint32_t i=0;i<3;++i)
    {
        auto phy=NrHelper::GetGnbPhy(gd.Get(i),0);
        auto cell=DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetCellId();
        NS_ABORT_MSG_IF(!phy->TraceConnectWithoutContext("SlotDataStats",MakeCallback(&Infrastructure::Slot,&infrastructure).Bind(phy)),"Missing real PRB hook");
        traces << "gNB," << gnbs.Get(i)->GetId() << ",,," << cell << ",0,SlotDataStats,NrGnbPhy\n";
        uint32_t hooked=0;
        for (uint32_t a=0;a<gnbs.Get(i)->GetNApplications();++a)
        {
            auto app=DynamicCast<NrEpcGnbApplication>(gnbs.Get(i)->GetApplication(a));
            if (app) { NS_ABORT_MSG_IF(!app->TraceConnectWithoutContext("RxFromS1u",MakeCallback(&Infrastructure::Ingress,&infrastructure).Bind(cell)),"Missing ingress hook"); ++hooked; }
        }
        NS_ABORT_MSG_IF(hooked!=1,"Expected exactly one EPC application per gNB");
        traces << "gNB," << gnbs.Get(i)->GetId() << ",,," << cell << ",0,RxFromS1u,NrEpcGnbApplication\n";
    }
    Open(config,output+"/run_config_v3.csv","scenario,duration_s,sampling_ms,seed,run,enable_handover,carrier_hz,bandwidth_hz,hysteresis_db,ttt_ms,traffic_interval_ms,udp_bytes,turn_s,stop_motion_s");
    config << "d2," << duration << "," << samplingMs << "," << seed << "," << run << "," << handover << ",3500000000,20000000,1.5,128,10,512," << turn << "," << 2*turn << "\n";
    Open(rrcReports,output+"/rrc_measurements_v3.csv","time_s,ue_id,imsi,serving_cell_id,rnti,meas_id,serving_rsrp_ie,neighbour_cell_id,neighbour_rsrp_ie");
    Open(registry,output+"/ue_registry_v3.csv","ue_id,imsi,node_id,ipv4,flow_id,destination_port,initial_cell_id,x0_m,y0_m,z0_m,vx_mps,vy_mps,vz_mps");
    Open(cells,output+"/cell_registry_v3.csv","gnb_id,node_id,cell_id,bwp_id,x_m,y_m,z_m");
    for (uint32_t i=0;i<3;++i) { cells << i << ',' << gnbs.Get(i)->GetId() << ',' << DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetCellId() << ",0," << sites[i].x << ',' << sites[i].y << ',' << sites[i].z << '\n'; }
    Open(packets,output+"/udp_packets_v3.csv","time_s,ue_id,imsi,flow_id,event,sequence,tx_time_s,udp_bytes,cell_id,rnti,valid");
    Open(events,output+"/handover_events_v3.csv","time_s,ue_id,imsi,attempt_id,event,source_cell_id,target_cell_id,rnti");
    Open(summary,output+"/udp_summary_v3.csv","ue_id,imsi,tx_packets,rx_packets,rx_unique,rx_bytes,lost_unique,final_cell_id,ho_starts,ho_ends,ho_errors,gnb_ends,active_attempt");
    Open(flows,output+"/flow_monitor_v3.csv","flow_monitor_id,ue_id,source_ip,destination_ip,source_port,destination_port,protocol,tx_packets,rx_packets,tx_ip_bytes,rx_ip_bytes,lost_packets,unresolved_packets");
    RadioMeasurementLogger radio(output+"/radio_measurements.csv");
    SinrMeasurementLogger sinr(output+"/sinr_measurements.csv");
    std::vector<std::unique_ptr<State>> states; Dispatcher dispatcher; dispatcher.measurements=&rrcReports;
    for (uint32_t i=0;i<5;++i)
    {
        auto s = std::make_unique<State>(); s->id=i; s->device=DynamicCast<NrUeNetDevice>(ud.Get(i));
        s->ip=ips.GetAddress(i); s->port=1234+i; s->packets=&packets; s->events=&events;
        dispatcher.byImsi.emplace(s->device->GetImsi(),s.get());
        infrastructure.byImsi.emplace(s->device->GetImsi(),i);
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
        uint32_t initial=(i<3 ? i : i==3 ? 2 : 0);
        infrastructure.byDestination.emplace(std::make_pair(s->ip,s->port),std::make_pair(i,s->device->GetImsi()));
        for (const auto* name : {"ConnectionEstablished","HandoverStart","HandoverEndOk","HandoverEndError"})
        { traces << "UE," << ues.Get(i)->GetId() << ',' << i << ',' << s->device->GetImsi() << ",,," << name << ",NrUeRrc\n"; }
        for (const auto* name : {"ReportUeMeasurements","DlDataSinr","DlCtrlSinr"})
        { traces << "UE," << ues.Get(i)->GetId() << ',' << i << ',' << s->device->GetImsi() << ",,0," << name << ",NrUePhy\n"; }
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
    for (uint32_t i=0;i<3;++i) { NS_ABORT_MSG_IF(!DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetRrc()->TraceConnectWithoutContext("HandoverEndOk",MakeCallback(&Dispatcher::End,&dispatcher)),"Missing gNB trace");
        NS_ABORT_MSG_IF(!DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetRrc()->TraceConnectWithoutContext("RecvMeasurementReport",MakeCallback(&Dispatcher::Measurement,&dispatcher)),"Missing RRC report trace");
        for (const auto* name : {"HandoverEndOk","RecvMeasurementReport"})
        { traces << "gNB," << gnbs.Get(i)->GetId() << ",,," << DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetCellId() << ",0," << name << ",NrGnbRrc\n"; }
    }
    for (uint32_t i=0;i<3;++i)
    {
        auto rrc=DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetRrc();
        for (const auto* name : {"HandoverFailureNoPreamble","HandoverFailureMaxRach","HandoverFailureLeaving","HandoverFailureJoining"})
        {
            NS_ABORT_MSG_IF(!rrc->TraceConnectWithoutContext(name,MakeCallback(&Infrastructure::Failure,&infrastructure).Bind(std::string(name))),"Missing native failure trace");
            traces << "gNB," << gnbs.Get(i)->GetId() << ",,," << DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetCellId() << ",0," << name << ",NrGnbRrc\n";
        }
    }
    Sampler sampler; sampler.states=&states; sampler.nodes=ues; sampler.stop=Seconds(duration); sampler.interval=MilliSeconds(samplingMs);
    Open(sampler.mobility,output+"/ue_mobility_v3.csv","time_s,ue_id,imsi,x_m,y_m,z_m,vx_mps,vy_mps,vz_mps,speed_mps,valid");
    Open(sampler.serving,output+"/serving_cells_v3.csv","time_s,ue_id,imsi,cell_id,rnti,rrc_state,connected");
    Simulator::ScheduleNow(&Sampler::Sample,&sampler);
    FlowMonitorHelper fm; NodeContainer endpoints; endpoints.Add(remote); endpoints.Add(ues);
    auto monitor=fm.Install(endpoints);
    monitor->SetAttribute("DelayBinWidth",DoubleValue(0.001));
    monitor->SetAttribute("JitterBinWidth",DoubleValue(0.001));
    monitor->SetAttribute("PacketSizeBinWidth",DoubleValue(20));
    Simulator::Stop(Seconds(duration)+NanoSeconds(1)); Simulator::Run(); monitor->CheckForLostPackets();
    auto classifier=DynamicCast<Ipv4FlowClassifier>(fm.GetClassifier());
    std::vector<uint64_t> ipTx(5),ipRx(5); std::set<uint32_t> mapped;
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
    bool ok=mapped.size()==5;
    for (const auto& s:states)
    {
        summary << s->id << ',' << s->device->GetImsi() << ',' << s->tx << ',' << s->rx << ',' << s->received.size() << ',' << s->bytes << ',' << s->tx-s->received.size() << ',' << s->device->GetRrc()->GetCellId()
                << ',' << s->starts << ',' << s->ends << ',' << s->errors << ',' << s->gnbEnds << ',' << s->active << '\n';
        ok = ok && s->attachments==1 && s->tx>0 && s->rx>0 && s->rx==s->received.size() && s->bytes==s->rx*512 &&
             ipTx[s->id]==s->tx && ipRx[s->id]==s->rx && !s->active && s->pendingGnb.empty() && !s->errors && s->starts==s->ends && s->ends==s->gnbEnds &&
             s->device->GetRrc()->GetState()==NrUeRrc::CONNECTED_NORMALLY;
        std::cout << "D2 UE=" << s->id << " IMSI=" << s->device->GetImsi() << " IP=" << s->ip << " TX=" << s->tx << " RX=" << s->rx << " HO=" << s->ends << " final_cell=" << s->device->GetRrc()->GetCellId() << '\n';
    }
    for (uint32_t i=0;i<3;++i)
    {
        auto phy=NrHelper::GetGnbPhy(gd.Get(i),0);
        auto id=DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetCellId();
        for (const auto* name : {"Numerology","TxPower"}) { Setting(settings,"gNB",id,phy,name,"explicit"); }
        for (const auto* name : {"NoiseFigure","Pattern"}) { Setting(settings,"gNB",id,phy,name,"library_default"); }
        auto rrc=DynamicCast<NrGnbNetDevice>(gd.Get(i))->GetRrc();
        for (const auto* name : {"RsrpFilterCoefficient","RsrqFilterCoefficient"}) { Setting(settings,"gNB_RRC",id,rrc,name,"library_default"); }
    }
    for (uint32_t i=0;i<5;++i)
    {
        auto phy=NrHelper::GetUePhy(ud.Get(i),0);
        for (const auto* name : {"TxPower","NoiseFigure","UeMeasurementsFilterPeriod"}) { Setting(settings,"UE",i,phy,name,"library_default"); }
    }
    for (const auto& [scope,devices] : std::vector<std::pair<std::string,NetDeviceContainer>>{{"gNB_array",gd},{"UE_array",ud}})
    {
        for (uint32_t i=0;i<devices.GetN();++i)
        {
            Ptr<NrPhy> phy = scope=="gNB_array" ? StaticCast<NrPhy>(NrHelper::GetGnbPhy(devices.Get(i),0)) : StaticCast<NrPhy>(NrHelper::GetUePhy(devices.Get(i),0));
            auto antenna=phy->GetSpectrumPhy()->GetAntenna();
            for (const auto* name : {"NumRows","NumColumns","BearingAngle","DowntiltAngle"}) { Setting(settings,scope,i,antenna,name,"library_default"); }
            PointerValue element; antenna->GetAttribute("AntennaElement",element);
            Setting(settings,scope+"_element",i,element.Get<Object>(),"Gain","library_default");
        }
    }
    auto path=DynamicCast<ThreeGppPropagationLossModel>(bwps.at(0).get()->GetChannel()->GetPropagationLossModel());
    NS_ABORT_MSG_IF(!path,"Unexpected D2 path loss model");
    Setting(settings,"channel",0,path,"Frequency","explicit");
    Setting(settings,"channel",0,path,"ShadowingEnabled","library_default");
    Setting(settings,"condition",0,path->GetChannelConditionModel(),"UpdatePeriod","library_default");
    auto spectrum=DynamicCast<ThreeGppSpectrumPropagationLossModel>(bwps.at(0).get()->GetChannel()->GetPhasedArraySpectrumPropagationLossModel());
    NS_ABORT_MSG_IF(!spectrum,"Unexpected D2 fading model");
    Setting(settings,"fading",0,spectrum->GetChannelModel(),"UpdatePeriod","library_default");
    for (const auto& s : states)
    {
        auto ueRrc=s->device->GetRrc();
        for (uint32_t i=0;i<3;++i)
        {
            auto device=DynamicCast<NrGnbNetDevice>(gd.Get(i));
            if (device->GetCellId()!=ueRrc->GetCellId()) { continue; }
            auto rrc=device->GetRrc(); auto rnti=ueRrc->GetRnti(); bool present=rrc->HasUeManager(rnti);
            contexts << Simulator::Now().GetSeconds() << ',' << s->id << ',' << s->device->GetImsi()
                     << ',' << ueRrc->GetCellId() << ',' << rnti << ',' << static_cast<int>(ueRrc->GetState()) << ',' << present << ',';
            if (present) { contexts << rrc->GetUeManager(rnti)->GetImsi(); }
            contexts << ',';
            if (present) { contexts << static_cast<int>(rrc->GetUeManager(rnti)->GetState()); }
            contexts << ',' << s->pendingGnb.size() << '\n';
        }
    }
    radio.Close(); sinr.Close();
    for (auto* stream : {&registry,&packets,&events,&summary,&flows,&cells,&sampler.mobility,&sampler.serving,&rrcReports,&config,&x2,&traces,&infrastructure.slots,&infrastructure.ingress,&settings,&contexts,&infrastructure.failures}) { stream->close(); NS_ABORT_MSG_IF(stream->fail(),"D2 CSV write failure"); }
    Simulator::Destroy();
    std::cout << "PHASE D2 PRODUCER CHECKS (offline gate still required): " << (ok ? "PASS" : "FAIL") << std::endl;
    return ok ? 0 : 1;
}
} // namespace d2
#endif
