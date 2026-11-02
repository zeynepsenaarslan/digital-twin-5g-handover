// SPDX-License-Identifier: GPL-2.0-only
#ifndef DT_D2_DIAGNOSTICS_H
#define DT_D2_DIAGNOSTICS_H
namespace d2
{
/** D2-only passive joining investigation; observations are passive unless the explicitly requested power probe is enabled. */
class JoiningDiagnostics
{
  public:
    /** @param directory Fresh diagnostics subdirectory. @param devices gNB devices. @param ue UE1 device. @param powerProbe Enable the opt-in causal experiment. */
    JoiningDiagnostics(const std::string& directory, NetDeviceContainer devices, Ptr<NrUeNetDevice> ue, bool powerProbe=false)
        : m_devices(devices), m_ue(ue), m_powerProbe(powerProbe)
    {
        std::filesystem::create_directory(directory);
        m_out.open(directory+"/timeline.csv");
        m_out << "sequence,time_ns,layer,event,imsi,cell_id,rnti,detail\n";
        auto rrc=ue->GetRrc();
        rrc->TraceConnectWithoutContext("StateTransition",MakeCallback(&JoiningDiagnostics::UeState,this));
        rrc->TraceConnectWithoutContext("RandomAccessSuccessful",MakeCallback(&JoiningDiagnostics::Ra,this));
        rrc->TraceConnectWithoutContext("Srb1Created",MakeCallback(&JoiningDiagnostics::UeBearer,this));
        auto up=ue->GetPhy(0)->GetSpectrumPhy();
        up->TraceConnectWithoutContext("TxDataTrace",MakeCallback(&JoiningDiagnostics::UeTx,this).Bind(up));
        auto mac=NrHelper::GetUeMac(ue,0);
        mac->TraceConnectWithoutContext("UeMacStateMachineTrace",MakeCallback(&JoiningDiagnostics::MacState,this));
        mac->TraceConnectWithoutContext("UeMacRxedCtrlMsgsTrace",MakeCallback(&JoiningDiagnostics::Control,this).Bind(std::string("RX")));
        mac->TraceConnectWithoutContext("UeMacTxedCtrlMsgsTrace",MakeCallback(&JoiningDiagnostics::Control,this).Bind(std::string("TX")));
        for (uint32_t i=0;i<devices.GetN();++i)
        {
            auto d=DynamicCast<NrGnbNetDevice>(devices.Get(i)); auto g=d->GetRrc(); auto cell=d->GetCellId();
            auto ip=d->GetNode()->GetObject<Ipv4L3Protocol>();
            ip->TraceConnectWithoutContext("Tx",MakeCallback(&JoiningDiagnostics::X2,this).Bind(cell,std::string("TX")));
            ip->TraceConnectWithoutContext("Rx",MakeCallback(&JoiningDiagnostics::X2,this).Bind(cell,std::string("RX")));
            g->TraceConnectWithoutContext("NewUeContext",MakeCallback(&JoiningDiagnostics::NewContext,this).Bind(g));
            g->TraceConnectWithoutContext("NotifyConnectionRelease",MakeCallback(&JoiningDiagnostics::Release,this).Bind(g));
            g->TraceConnectWithoutContext("HandoverStart",MakeCallback(&JoiningDiagnostics::Command,this));
            g->TraceConnectWithoutContext("RxRrcConnectionReconfigurationCompleted",MakeCallback(&JoiningDiagnostics::Complete,this).Bind(g,cell));
            g->TraceConnectWithoutContext("HandoverFailureJoining",MakeCallback(&JoiningDiagnostics::Failure,this).Bind(g));
            auto sp=NrHelper::GetGnbPhy(d,0)->GetSpectrumPhy();
            sp->TraceConnectWithoutContext("RxPacketTraceGnb",MakeCallback(&JoiningDiagnostics::Phy,this).Bind(g));
            sp->TraceConnectWithoutContext("TxDataTrace",MakeCallback(&JoiningDiagnostics::GnbTx,this).Bind(cell,sp));
            sp->GetNrInterference()->TraceConnectWithoutContext("SnrPerProcessedChunk",MakeCallback(&JoiningDiagnostics::Snr,this).Bind(cell));
            NrHelper::GetGnbMac(d,0)->TraceConnectWithoutContext("UlScheduling",MakeCallback(&JoiningDiagnostics::Scheduling,this).Bind(g,cell));
        }
    }
    /** Close after Simulator::Run and before simulator destruction. */
    void Close() { m_out.close(); NS_ABORT_MSG_IF(m_out.fail(),"D2 diagnostic write failed"); }
  private:
    /** Bearer identity bound to the object lifetime, never a global RNTI key. */
    struct Endpoint
    {
        NrUeManager* manager; ///< Non-owning manager; callback dies with its bearer.
        uint16_t cell; ///< Cell at bearer creation.
        std::string role; ///< UE or gNB.
    };
    NetDeviceContainer m_devices; ///< gNB registry.
    Ptr<NrUeNetDevice> m_ue; ///< UE1 stable device identity.
    std::ofstream m_out; ///< Ordered native event stream.
    bool m_powerProbe; ///< Opt-in causal experiment; never used by the release profile.
    uint64_t m_sequence{}; ///< Total observation order.
    std::vector<std::unique_ptr<Endpoint>> m_endpoints; ///< Callback context ownership.
    /** @return Whether the fixed investigation window is active. */
    bool Window() const { auto t=Simulator::Now().GetSeconds(); return t>=37 && t<=50.2; }
    /** @param layer Native layer. @param event Observed event. @param imsi Native identity. @param cell Cell. @param rnti Local RNTI. @param detail ASCII scalar details. */
    void Write(std::string layer,std::string event,uint64_t imsi,uint16_t cell,uint16_t rnti,std::string detail="")
    {
        if (!Window()) { return; }
        m_out << m_sequence++ << ',' << Simulator::Now().GetNanoSeconds() << ',' << layer << ',' << event << ','
              << imsi << ',' << cell << ',' << rnti << ',' << detail << '\n';
    }
    /** @param e Bound endpoint. @return Current native IMSI of that object. */
    uint64_t Imsi(Endpoint* e) { return e->manager ? e->manager->GetImsi() : m_ue->GetImsi(); }
    /** @param e Bound endpoint. @param layer PDCP/RLC. @param rnti Native RNTI. @param lcid Native LCID. @param size PDU bytes. */
    void Tx(Endpoint* e,std::string layer,uint16_t rnti,uint8_t lcid,uint32_t size)
    {
        if (Imsi(e)==m_ue->GetImsi()) { Write(e->role+"_"+layer,"TX",Imsi(e),e->cell,rnti,"lcid="+std::to_string(lcid)+";bytes="+std::to_string(size)); }
    }
    /** @param e Bound endpoint. @param layer PDCP/RLC. @param rnti Native RNTI. @param lcid Native LCID. @param size PDU bytes. @param delay Native delay ns. */
    void Rx(Endpoint* e,std::string layer,uint16_t rnti,uint8_t lcid,uint32_t size,uint64_t delay)
    {
        if (Imsi(e)==m_ue->GetImsi()) { Write(e->role+"_"+layer,"RX",Imsi(e),e->cell,rnti,"lcid="+std::to_string(lcid)+";bytes="+std::to_string(size)+";delay_ns="+std::to_string(delay)); }
    }
    /** @param object Object owning the Srb1 attribute. @param manager Optional manager. @param cell Bound cell. @param role UE/gNB. */
    void Bearer(Ptr<Object> object,Ptr<NrUeManager> manager,uint16_t cell,std::string role)
    {
        PointerValue value;object->GetAttribute("Srb1",value);auto s=value.Get<NrSignalingRadioBearerInfo>();
        if (!s) { return; }
        auto e=std::make_unique<Endpoint>();e->manager=PeekPointer(manager);e->cell=cell;e->role=role;auto ptr=e.get();
        s->m_pdcp->TraceConnectWithoutContext("TxPDU",MakeCallback(&JoiningDiagnostics::Tx,this).Bind(ptr,std::string("PDCP")));
        s->m_pdcp->TraceConnectWithoutContext("RxPDU",MakeCallback(&JoiningDiagnostics::Rx,this).Bind(ptr,std::string("PDCP")));
        s->m_rlc->TraceConnectWithoutContext("TxPDU",MakeCallback(&JoiningDiagnostics::Tx,this).Bind(ptr,std::string("RLC")));
        s->m_rlc->TraceConnectWithoutContext("RxPDU",MakeCallback(&JoiningDiagnostics::Rx,this).Bind(ptr,std::string("RLC")));
        m_endpoints.push_back(std::move(e));
    }
    /** @param imsi UE IMSI. @param cell Current cell. @param rnti Current RNTI. */
    void UeBearer(uint64_t imsi,uint16_t cell,uint16_t rnti) { Bearer(m_ue->GetRrc(),nullptr,cell,"UE"); Write("UE_RRC","SRB1_CREATED",imsi,cell,rnti); }
    /** @param g gNB RRC. @param cell Native cell. @param rnti Created context. */
    void NewContext(Ptr<NrGnbRrc> g,uint16_t cell,uint16_t rnti)
    {
        auto manager=g->GetUeManager(rnti);
        manager->TraceConnectWithoutContext("StateTransition",MakeCallback(&JoiningDiagnostics::GnbState,this));
        Bearer(manager,manager,cell,"gNB");
        Write("gNB_RRC","CONTEXT_CREATED",manager->GetImsi(),cell,rnti,"state="+std::to_string(manager->GetState()));
        Simulator::ScheduleNow(&JoiningDiagnostics::Snapshot,this,g,cell,rnti,std::string("AFTER_CREATE"));
    }
    /** @param g gNB RRC. @param cell Cell. @param rnti Context key. @param event Snapshot label. */
    void Snapshot(Ptr<NrGnbRrc> g,uint16_t cell,uint16_t rnti,std::string event)
    {
        bool present=g->HasUeManager(rnti);
        auto imsi=present ? g->GetUeManager(rnti)->GetImsi() : 0;
        Write("gNB_RRC",event,imsi,cell,rnti,"present="+std::to_string(present)+(present ? ";state="+std::to_string(g->GetUeManager(rnti)->GetState()) : ""));
    }
    /** @param g Reporting gNB. @param imsi Released IMSI. @param cell Cell. @param rnti Local key. */
    void Release(Ptr<NrGnbRrc> g,uint64_t imsi,uint16_t cell,uint16_t rnti)
    {
        if (imsi!=m_ue->GetImsi()) { return; }
        Snapshot(g,cell,rnti,"RELEASE_BEFORE_ERASE");
        Simulator::ScheduleNow(&JoiningDiagnostics::Snapshot,this,g,cell,rnti,std::string("AFTER_ERASE"));
    }
    /** @param g Reporting gNB. @param imsi Failed IMSI. @param rnti Local key. @param cell Cell. */
    void Failure(Ptr<NrGnbRrc> g,uint64_t imsi,uint16_t rnti,uint16_t cell) { if (imsi==m_ue->GetImsi()) { Snapshot(g,cell,rnti,"JOIN_TIMEOUT_FIRED"); } }
    /** @param imsi IMSI. @param cell Cell. @param rnti Source key. @param target Target cell. */
    void Command(uint64_t imsi,uint16_t cell,uint16_t rnti,uint16_t target) { if (imsi==m_ue->GetImsi()) { Write("gNB_RRC","HO_COMMAND_DISPATCH",imsi,cell,rnti,"target="+std::to_string(target)); } }
    /** @param g Reporting RRC. @param cell Cell. @param rnti Native received key. */
    void Complete(Ptr<NrGnbRrc> g,uint16_t cell,uint16_t rnti) { if (g->HasUeManager(rnti) && g->GetUeManager(rnti)->GetImsi()==m_ue->GetImsi()) { Write("gNB_RRC","RECONFIG_COMPLETE_RECEIVED",m_ue->GetImsi(),cell,rnti); } }
    /** @param imsi IMSI. @param cell Cell. @param rnti Key. @param old Old state. @param state New state. */
    void UeState(uint64_t imsi,uint16_t cell,uint16_t rnti,NrUeRrc::State old,NrUeRrc::State state) { Write("UE_RRC","STATE",imsi,cell,rnti,std::to_string(old)+";"+std::to_string(state)); }
    /** @param imsi IMSI. @param cell Cell. @param rnti Key. @param old Old state. @param state New state. */
    void GnbState(uint64_t imsi,uint16_t cell,uint16_t rnti,NrUeManager::State old,NrUeManager::State state) { if (imsi==m_ue->GetImsi()) { Write("gNB_RRC","STATE",imsi,cell,rnti,std::to_string(old)+";"+std::to_string(state)); } }
    /** @param imsi IMSI. @param cell Cell. @param rnti Native key. */
    void Ra(uint64_t imsi,uint16_t cell,uint16_t rnti)
    {
        Write("UE_MAC","RA_SUCCESS",imsi,cell,rnti);
        if (m_powerProbe && cell==2 && rnti==5 && Simulator::Now()>Seconds(49) && Simulator::Now()<Seconds(50))
        {
            auto phy=m_ue->GetPhy(0); auto before=phy->GetTxPower(); phy->SetTxPower(23);
            Write("EXPERIMENT","UE_POWER_STEP",imsi,cell,rnti,"before_dbm="+std::to_string(before)+";after_dbm=23");
            m_powerProbe=false;
        }
    }
    /** @param direction RX/TX. @param imsi IMSI. @param slot Slot. @param cell Cell. @param rnti Key. @param bwp BWP. @param message Control message. */
    void Control(std::string direction,uint64_t imsi,SfnSf slot,uint16_t cell,uint16_t rnti,uint8_t bwp,Ptr<const NrControlMessage> message)
    { Write("UE_MAC",direction+"_CONTROL",imsi,cell,rnti,"type="+std::to_string(message->GetMessageType())+";slot="+std::to_string(slot.Normalize())); }
    /** @param imsi IMSI. @param slot Slot. @param cell Cell. @param rnti Key. @param bwp BWP. @param state SR/BSR state. @param buffers Native queue reports. @param retx Retx flag. @param function Producer label. */
    void MacState(uint64_t imsi,SfnSf slot,uint16_t cell,uint16_t rnti,uint8_t bwp,NrUeMac::SrBsrMachine state,std::unordered_map<uint8_t,NrMacSapProvider::BufferStatusReportParameters> buffers,int retx,std::string function)
    {
        std::string detail="state="+std::to_string(state)+";function="+function;
        for (const auto& [lc,b] : buffers) { detail+=";lc="+std::to_string(lc)+":tx="+std::to_string(b.txQueueSize)+":retx="+std::to_string(b.retxQueueSize)+":status="+std::to_string(b.statusPduSize); }
        Write("UE_MAC","BUFFERS",imsi,cell,rnti,detail);
    }
    /** @param cell Bound cell. @param direction RX/TX. @param packet Native IP packet. @param ip IP instance. @param interface Native interface. */
    void X2(uint16_t cell,std::string direction,Ptr<const Packet> packet,Ptr<Ipv4> ip,uint32_t interface)
    {
        if (!Window()) { return; }
        auto copy=packet->Copy();Ipv4Header header;UdpHeader udp;
        if (!copy->RemoveHeader(header) || header.GetProtocol()!=17 || !copy->RemoveHeader(udp) || udp.GetDestinationPort()!=4444) { return; }
        NrEpcX2Header x2;copy->RemoveHeader(x2);
        std::ostringstream detail;detail << "src=" << header.GetSource() << ";dst=" << header.GetDestination()
            << ";procedure=" << +x2.GetProcedureCode() << ";type=" << +x2.GetMessageType();
        Write("X2_IP",direction,0,cell,0,detail.str());
    }
    /** @param g Bound RRC. @param cell Cell. @param info Actual UL scheduling record. */
    void Scheduling(Ptr<NrGnbRrc> g,uint16_t cell,NrSchedulingCallbackInfo info)
    {
        if (g->HasUeManager(info.m_rnti) && g->GetUeManager(info.m_rnti)->GetImsi()==m_ue->GetImsi())
        { Write("gNB_MAC","UL_GRANT",m_ue->GetImsi(),cell,info.m_rnti,"bytes="+std::to_string(info.m_tbSize)+";rv="+std::to_string(info.m_rv)+";slot="+std::to_string(info.m_frameNum*20+info.m_subframeNum*2+info.m_slotNum)); }
    }
    /** @param cell Receiver cell. @param value Native full-band S/N ratio. */
    void Snr(uint16_t cell,double value) { Write("gNB_PHY","SNR",0,cell,0,"linear="+std::to_string(value)); }
    /** @param cell Transmitter cell. @param phy Actual transmitter. @param duration Actual TX interval. */
    void GnbTx(uint16_t cell,Ptr<NrSpectrumPhy> phy,Time duration)
    {
        if (!Window()) { return; }
        auto watts=Integral(*phy->GetTxPowerSpectralDensity());
        Write("gNB_PHY","DL_TX",0,cell,0,"duration_ns="+std::to_string(duration.GetNanoSeconds())+";dbm="+std::to_string(10*std::log10(watts)+30));
    }
    /** @param phy Actual UE PHY. @param duration Actual TX interval. */
    void UeTx(Ptr<NrSpectrumPhy> phy,Time duration)
    {
        if (!Window()) { return; }
        auto watts=Integral(*phy->GetTxPowerSpectralDensity());auto rrc=m_ue->GetRrc();
        Write("UE_PHY","UL_TX",rrc->GetImsi(),rrc->GetCellId(),rrc->GetRnti(),"duration_ns="+std::to_string(duration.GetNanoSeconds())+";dbm="+std::to_string(10*std::log10(watts)+30));
    }
    /** @param g Bound RRC. @param p Actual decoded/corrupt TB record. */
    void Phy(Ptr<NrGnbRrc> g,RxPacketTraceParams p)
    {
        auto imsi=g->HasUeManager(p.m_rnti) ? g->GetUeManager(p.m_rnti)->GetImsi() : 0;
        if (imsi==m_ue->GetImsi()) { Write("gNB_PHY","UL_TB",imsi,p.m_cellId,p.m_rnti,"bytes="+std::to_string(p.m_tbSize)+";corrupt="+std::to_string(p.m_corrupt)+";sinr="+std::to_string(p.m_sinr)+";rv="+std::to_string(p.m_rv)+";rb="+std::to_string(p.m_rbAssignedNum)+";tbler="+std::to_string(p.m_tbler)); }
    }
};
}
#endif
