/*
 * dt-handover-simulation.cc
 *
 * Phase A: Topology, UE mobility and CSV logging.
 * Phase B1: NR attachment and EPC IPv4 configuration.
 * Phase B2: Downlink UDP traffic and measured packet delivery.
 * Phase B3: Optional measurement-triggered A3-RSRP X2 handover with real RRC.
 */

#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/nr-module.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("DtHandoverSimulation");

namespace
{

/** Passively write the existing UE PHY measurement trace as two metric rows. */
class RadioMeasurementLogger
{
  public:
    /**
     * Open a new radio measurement stream.
     * @param path CSV output path.
     */
    explicit RadioMeasurementLogger(const std::string& path)
        : m_out(path)
    {
        NS_ABORT_MSG_IF(!m_out, "Cannot open " << path);
        m_out << "time_ns,time_s,ue_id,imsi,rnti,bwp_id,serving_cell_id,measured_cell_id,"
                 "is_serving,metric,value,unit,source\n";
    }

    /**
     * Observe ReportUeMeasurements without modifying its producer or RRC state.
     * @param ue UE device bound when connecting the callback.
     * @param ueId UE index used in the mobility CSV.
     * @param rnti RNTI reported by the PHY.
     * @param measuredCell Cell whose signal was measured.
     * @param rsrp L1 averaged RSRP in dBm, before RRC quantization.
     * @param rsrq Model-derived RSRQ in dB, before RRC quantization.
     * @param isServing Whether measuredCell is the PHY serving cell.
     * @param bwpId Reported component carrier/BWP identifier.
     */
    void Record(Ptr<NrUeNetDevice> ue, uint32_t ueId, uint16_t rnti,
                uint16_t measuredCell, double rsrp, double rsrq, bool isServing,
                uint8_t bwpId)
    {
        // Read the same PHY cell identity used by the trace's serving flag.
        const uint16_t servingCell = ue->GetPhy(bwpId)->GetCellId();
        const Time now = Simulator::Now();
        Write(now, ueId, ue->GetImsi(), rnti, bwpId, servingCell, measuredCell,
              isServing, "rsrp", rsrp, "dBm");
        Write(now, ueId, ue->GetImsi(), rnti, bwpId, servingCell, measuredCell,
              isServing, "rsrq_model_derived", rsrq, "dB");
    }

    /** Close and verify the output stream after the simulation ends. */
    void Close()
    {
        m_out.close();
        NS_ABORT_MSG_IF(m_out.fail(), "Radio CSV write failed");
    }

  private:
    /**
     * Write one metric in native units without scheduling any simulator event.
     * @param now Simulator timestamp.
     * @param ueId Mobility CSV UE index.
     * @param imsi Full-width UE IMSI.
     * @param rnti PHY RNTI.
     * @param bwp BWP identifier.
     * @param serving Current PHY serving cell.
     * @param measured Measured cell identifier.
     * @param isServing Original trace serving flag.
     * @param metric Metric name.
     * @param value Unmodified reported value.
     * @param unit Native physical unit.
     */
    void Write(Time now, uint32_t ueId, uint64_t imsi, uint16_t rnti, uint8_t bwp,
               uint16_t serving, uint16_t measured, bool isServing, const char* metric,
               double value, const char* unit)
    {
        m_out << now.GetNanoSeconds() << ',' << std::fixed << std::setprecision(9)
              << now.GetSeconds() << ',' << ueId << ',' << imsi << ',' << rnti << ','
              << unsigned(bwp) << ',' << serving << ',' << measured << ',' << isServing
              << ',' << metric << ',' << std::setprecision(17) << value << ',' << unit
              << ",NrUePhy::ReportUeMeasurements\n";
    }

    std::ofstream m_out; ///< Passive radio measurement CSV stream.
};

/** Record the successful UE RRC connection event for Phase B1 validation. */
struct AttachmentRecord
{
    uint32_t count{0}; ///< Number of connection establishment events.
    uint64_t imsi{0}; ///< IMSI reported by RRC.
    uint16_t cellId{0}; ///< Serving cell reported by RRC.
    uint16_t rnti{0}; ///< RNTI assigned to the UE.
};

/**
 * Log successful RRC attachment.
 * @param record Attachment result to update.
 * @param imsi UE IMSI.
 * @param cellId Serving cell identifier.
 * @param rnti Assigned RNTI.
 */
void RecordAttachment(AttachmentRecord* record, uint64_t imsi, uint16_t cellId, uint16_t rnti)
{
    ++record->count;
    record->imsi = imsi;
    record->cellId = cellId;
    record->rnti = rnti;
    std::cout << "NR ConnectionEstablished: time_s=" << Simulator::Now().GetSeconds()
              << " IMSI=" << imsi << " cellId=" << cellId << " RNTI=" << rnti << '\n';
}

/** Capture actual RRC events and measurement reports for one UE handover. */
class HandoverLogger
{
  public:
    /**
     * Open the trace CSV streams.
     * @param directory Output directory.
     * @param source Expected source cell identifier.
     * @param target Expected target cell identifier.
     */
    HandoverLogger(const std::string& directory, uint16_t source, uint16_t target)
        : m_events(directory + "/handover_events.csv"),
          m_measurements(directory + "/handover_measurements.csv"),
          m_expectedSource(source), m_expectedTarget(target)
    {
        NS_ABORT_MSG_IF(!m_events || !m_measurements, "Cannot open handover CSV files");
        m_events << "time_s,event,imsi,source_cell_id,target_cell_id,rnti\n";
        m_measurements << "time_s,imsi,serving_cell_id,rnti,meas_id,serving_rsrp_ie,"
                          "neighbour_cell_id,neighbour_rsrp_ie\n";
    }

    /**
     * Record the UE HandoverStart trace.
     * @param imsi UE IMSI.
     * @param cell Source cell.
     * @param rnti Source RNTI.
     * @param target Target cell.
     */
    void Start(uint64_t imsi, uint16_t cell, uint16_t rnti, uint16_t target)
    {
        ++starts;
        startTime = Simulator::Now();
        sourceCell = cell;
        targetCell = target;
        ueImsi = imsi;
        Write("UE_HandoverStart", imsi, cell, target, rnti);
    }

    /**
     * Record successful UE handover termination.
     * @param imsi UE IMSI.
     * @param cell Current target cell.
     * @param rnti Target RNTI.
     */
    void End(uint64_t imsi, uint16_t cell, uint16_t rnti)
    {
        ++ends;
        endTime = Simulator::Now();
        endCell = cell;
        endRnti = rnti;
        consistent = consistent && starts == 1 && imsi == ueImsi && cell == targetCell;
        Write("UE_HandoverEndOk", imsi, sourceCell, cell, rnti);
    }

    /**
     * Record target gNB handover completion.
     * @param imsi UE IMSI.
     * @param cell Target cell.
     * @param rnti Target RNTI.
     */
    void GnbEnd(uint64_t imsi, uint16_t cell, uint16_t rnti)
    {
        ++gnbEnds;
        consistent = consistent && ends == 1 && imsi == ueImsi && cell == endCell &&
                     rnti == endRnti;
        Write("gNB_HandoverEndOk", imsi, sourceCell, cell, rnti);
    }

    /**
     * Record a UE handover error.
     * @param imsi UE IMSI.
     * @param cell Cell reported by the error trace.
     * @param rnti RNTI reported by the error trace.
     */
    void Error(uint64_t imsi, uint16_t cell, uint16_t rnti)
    {
        ++errors;
        consistent = consistent && (cell == sourceCell || cell == targetCell);
        Write("UE_HandoverEndError", imsi, sourceCell, targetCell, rnti);
    }

    /**
     * Record received RRC measurements in their native quantized IE units.
     * @param imsi UE IMSI.
     * @param cell Reporting serving cell.
     * @param rnti UE RNTI.
     * @param report Actual received measurement report.
     */
    void Measurement(uint64_t imsi, uint16_t cell, uint16_t rnti,
                     NrRrcSap::MeasurementReport report)
    {
        ++reports;
        const auto& results = report.measResults;
        for (const auto& neighbour : results.measResultListEutra)
        {
            if (!neighbour.haveRsrpResult)
            {
                continue;
            }
            m_measurements << std::fixed << std::setprecision(9)
                           << Simulator::Now().GetSeconds() << ',' << imsi << ',' << cell << ','
                           << rnti << ',' << unsigned(results.measId) << ','
                           << unsigned(results.measResultPCell.rsrpResult) << ','
                           << neighbour.physCellId << ',' << unsigned(neighbour.rsrpResult) << '\n';
            if (cell == m_expectedSource && neighbour.physCellId == m_expectedTarget)
            {
                ++sourceToTargetReports;
                lastSourceReport = Simulator::Now();
                reportImsi = imsi;
            }
        }
    }

    /** Close and verify the trace CSV streams. */
    void Close()
    {
        m_events.close();
        m_measurements.close();
        NS_ABORT_MSG_IF(m_events.fail() || m_measurements.fail(), "Handover CSV write failed");
    }

    uint32_t starts{0}; ///< Observed UE start events.
    uint32_t ends{0}; ///< Observed UE successful end events.
    uint32_t gnbEnds{0}; ///< Observed target gNB successful end events.
    uint32_t errors{0}; ///< Observed UE error events.
    uint32_t reports{0}; ///< Received measurement reports.
    uint32_t sourceToTargetReports{0}; ///< Measurement rows from source concerning target.
    Time lastSourceReport; ///< Most recent actual source-to-target measurement report.
    uint64_t reportImsi{0}; ///< IMSI in the source-to-target report.
    Time startTime; ///< Actual UE handover start.
    Time endTime; ///< Actual UE handover completion.
    uint16_t sourceCell{0}; ///< Source cell from start trace.
    uint16_t targetCell{0}; ///< Target cell from start trace.
    uint16_t endCell{0}; ///< Cell from completion trace.
    uint16_t endRnti{0}; ///< RNTI from completion trace.
    uint64_t ueImsi{0}; ///< IMSI from start trace.
    bool consistent{true}; ///< Trace identities and ordering agree.

  private:
    /**
     * Write one trace event.
     * @param event Actual trace source label.
     * @param imsi UE IMSI.
     * @param source Source cell paired with the start event.
     * @param target Target or reported current cell.
     * @param rnti RNTI from this event.
     */
    void Write(const char* event, uint64_t imsi, uint16_t source, uint16_t target, uint16_t rnti)
    {
        m_events << std::fixed << std::setprecision(9) << Simulator::Now().GetSeconds() << ','
                 << event << ',' << imsi << ',' << source << ',' << target << ',' << rnti << '\n';
        std::cout << event << ": time_s=" << std::setprecision(9)
                  << Simulator::Now().GetSeconds() << " IMSI=" << imsi << " source=" << source
                  << " target=" << target << " RNTI=" << rnti << '\n';
    }
    std::ofstream m_events; ///< Real RRC event CSV.
    std::ofstream m_measurements; ///< Real received RRC measurement CSV.
    uint16_t m_expectedSource; ///< Expected source cell identifier.
    uint16_t m_expectedTarget; ///< Expected target cell identifier.
};

/** Log cumulative UDP counters once per second, without retaining packet data. */
class UdpTrafficLogger
{
  public:
    /**
     * Construct the logger.
     * @param client Sender with a successful-send byte counter.
     * @param start Traffic start time.
     * @param end Traffic generation end time.
     * @param stop Simulation end time.
     * @param path CSV output path.
     * @param packetPath Per-packet reception CSV output path.
     */
    UdpTrafficLogger(Ptr<UdpClient> client, Time start, Time end, Time stop,
                     const std::string& path, const std::string& packetPath)
        : m_client(client), m_start(start), m_end(end), m_stop(stop), m_out(path),
          m_packets(packetPath)
    {
        NS_ABORT_MSG_IF(!m_out.is_open(), "Cannot open " << path);
        NS_ABORT_MSG_IF(!m_packets.is_open(), "Cannot open " << packetPath);
        m_out << "time_s,tx_packets,rx_packets,rx_bytes,pdr,average_throughput_mbps\n";
        m_packets << "rx_time_s,sequence,tx_time_s,udp_bytes\n";
    }

    /**
     * Count bytes from an actual UDP datagram, including its SeqTsHeader.
     * @param packet Received UDP datagram before its application header is removed.
     */
    void Receive(Ptr<const Packet> packet)
    {
        ++m_rxPackets;
        m_rxBytes += packet->GetSize();
        m_lastRx = Simulator::Now();
        SeqTsHeader header;
        packet->PeekHeader(header);
        m_packets << std::fixed << std::setprecision(9) << m_lastRx.GetSeconds() << ','
                  << header.GetSeq() << ',' << header.GetTs().GetSeconds() << ','
                  << packet->GetSize() << '\n';
    }

    /** Start periodic measurement. */
    void Start()
    {
        Simulator::ScheduleNow(&UdpTrafficLogger::Sample, this);
    }

    /** Close and check the CSV stream after simulation. */
    void Close()
    {
        m_out.close();
        m_packets.close();
        NS_ABORT_MSG_IF(m_out.fail() || m_packets.fail(), "UDP CSV write failed");
    }

    /** @return Number of successfully submitted 512-byte UDP datagrams. */
    uint64_t GetTxPackets() const { return m_client->GetTotalTx() / PACKET_SIZE; }
    /** @return Number of observed UDP receive events. */
    uint64_t GetRxPackets() const { return m_rxPackets; }
    /** @return Received UDP bytes, including SeqTsHeader but excluding UDP/IP headers. */
    uint64_t GetRxBytes() const { return m_rxBytes; }
    /** @return Time of the most recent actual packet reception. */
    Time GetLastRx() const { return m_lastRx; }
    /** @return Received/successfully transmitted packet ratio. */
    double GetPdr() const
    {
        return GetTxPackets() ? static_cast<double>(m_rxPackets) / GetTxPackets() : 0.0;
    }
    /** @return Mean received Mbit/s over the elapsed traffic generation window. */
    double GetThroughput() const
    {
        const double elapsed = (std::min(Simulator::Now(), m_end) - m_start).GetSeconds();
        return elapsed > 0 ? m_rxBytes * 8.0 / elapsed / 1e6 : 0.0;
    }

    static constexpr uint32_t PACKET_SIZE = 512; ///< UDP datagram size in bytes.

  private:
    /** Write actual cumulative counters and schedule the next measurement. */
    void Sample()
    {
        m_out << std::fixed << std::setprecision(9) << Simulator::Now().GetSeconds() << ','
              << GetTxPackets() << ',' << m_rxPackets << ',' << m_rxBytes << ','
              << GetPdr() << ',' << GetThroughput() << '\n';
        if (Simulator::Now() + Seconds(1) <= m_stop)
        {
            Simulator::Schedule(Seconds(1), &UdpTrafficLogger::Sample, this);
        }
    }

    Ptr<UdpClient> m_client; ///< UDP sender.
    Time m_start; ///< Traffic generation start.
    Time m_end; ///< Traffic generation end.
    Time m_stop; ///< Simulation end.
    std::ofstream m_out; ///< Traffic CSV stream.
    std::ofstream m_packets; ///< Per-packet receive timestamps and sequence identifiers.
    Time m_lastRx; ///< Last observed reception time.
    uint64_t m_rxPackets{0}; ///< Measured receive event count.
    uint64_t m_rxBytes{0}; ///< Measured UDP bytes received.
};

struct MobilitySample
{
    int64_t timeNs;
    uint32_t ueId;
    Vector position;
    double speed;
};

class UeMobilityLogger
{
  public:
    UeMobilityLogger(const NodeContainer& ues,
                     Time interval,
                     Time stopTime,
                     const std::string& csvPath)
        : m_ues(ues),
          m_interval(interval),
          m_stop(stopTime)
    {
        m_out.open(csvPath);
        NS_ABORT_MSG_IF(!m_out.is_open(), "Cannot open " << csvPath);

        m_out << "time_s,ue_id,x_m,y_m,z_m,speed_mps\n";
    }

    void Start()
    {
        Simulator::ScheduleNow(&UeMobilityLogger::Sample, this);
    }

    void Close()
    {
        m_out.close();
    }

    const std::vector<MobilitySample>& GetSamples() const
    {
        return m_samples;
    }

  private:
    void Sample()
    {
        const Time now = Simulator::Now();

        for (uint32_t i = 0; i < m_ues.GetN(); ++i)
        {
            Ptr<MobilityModel> mm =
                m_ues.Get(i)->GetObject<MobilityModel>();

            NS_ABORT_MSG_IF(!mm, "UE " << i << " has no MobilityModel");

            const Vector p = mm->GetPosition();
            const double speed = mm->GetVelocity().GetLength();

            m_samples.push_back({
                now.GetNanoSeconds(),
                i,
                p,
                speed
            });

            m_out << std::fixed
                  << std::setprecision(3)
                  << now.GetSeconds() << ','
                  << i << ','
                  << std::setprecision(4)
                  << p.x << ','
                  << p.y << ','
                  << p.z << ','
                  << speed << '\n';
        }

        if (now + m_interval <= m_stop)
        {
            Simulator::Schedule(
                m_interval,
                &UeMobilityLogger::Sample,
                this);
        }
    }

    NodeContainer m_ues;
    Time m_interval;
    Time m_stop;

    std::ofstream m_out;
    std::vector<MobilitySample> m_samples;
};

} // namespace

int main(int argc, char* argv[])
{
    // Configurable parameters
    uint32_t seed = 1;
    uint32_t run = 1;

    double ueSpeed = 5.0;
    double gnbSeparation = 300.0;
    double simTime = 30.0;

    uint32_t samplingMs = 30;

    double gnbHeight = 25.0;
    double ueHeight = 1.5;

    double ueStartX = 20.0;
    double ueOffsetY = 20.0;

    std::string outputDir = "dt-output";
    bool enableHandover = false;

    CommandLine cmd(__FILE__);

    cmd.AddValue("seed", "RNG seed", seed);
    cmd.AddValue("run", "RNG run number", run);
    cmd.AddValue("ueSpeed", "UE speed along +x [m/s]", ueSpeed);
    cmd.AddValue("gnbSeparation", "Distance between gNBs [m]", gnbSeparation);
    cmd.AddValue("simTime", "Simulation duration [s]", simTime);
    cmd.AddValue("samplingMs", "Sampling interval [ms]", samplingMs);
    cmd.AddValue("gnbHeight", "gNB height [m]", gnbHeight);
    cmd.AddValue("ueHeight", "UE height [m]", ueHeight);
    cmd.AddValue("ueStartX", "Initial UE x position [m]", ueStartX);
    cmd.AddValue("ueOffsetY", "UE y position [m]", ueOffsetY);
    cmd.AddValue("outputDir", "CSV output directory", outputDir);
    cmd.AddValue("enableHandover", "Enable A3-RSRP X2 handover and real RRC (B3)", enableHandover);

    cmd.Parse(argc, argv);

    NS_ABORT_MSG_IF(samplingMs == 0, "samplingMs must be > 0");
    NS_ABORT_MSG_IF(simTime <= 0.0, "simTime must be > 0");
    NS_ABORT_MSG_IF(simTime <= 2.0, "Phase B2 needs simTime > 2 s for startup and drain");

    RngSeedManager::SetSeed(seed);
    RngSeedManager::SetRun(run);

    NS_ABORT_MSG_IF(std::filesystem::exists(outputDir + "/ue_mobility.csv") ||
                        std::filesystem::exists(outputDir + "/udp_traffic.csv") ||
                        std::filesystem::exists(outputDir + "/udp_packets.csv") ||
                        std::filesystem::exists(outputDir + "/handover_events.csv") ||
                        std::filesystem::exists(outputDir + "/handover_measurements.csv") ||
                        std::filesystem::exists(outputDir + "/radio_measurements.csv"),
                    "Output CSV already exists; select a fresh --outputDir to preserve results");
    std::filesystem::create_directories(outputDir);

    // Create nodes
    NodeContainer gnbNodes;
    gnbNodes.Create(2);

    NodeContainer ueNodes;
    ueNodes.Create(1);

    // Fixed gNB positions
    Ptr<ListPositionAllocator> gnbPos =
        CreateObject<ListPositionAllocator>();

    gnbPos->Add(Vector(0.0, 0.0, gnbHeight));
    gnbPos->Add(Vector(gnbSeparation, 0.0, gnbHeight));

    MobilityHelper gnbMobility;

    gnbMobility.SetMobilityModel(
        "ns3::ConstantPositionMobilityModel");

    gnbMobility.SetPositionAllocator(gnbPos);
    gnbMobility.Install(gnbNodes);

    // Moving UE
    Ptr<ListPositionAllocator> uePos =
        CreateObject<ListPositionAllocator>();

    uePos->Add(Vector(ueStartX, ueOffsetY, ueHeight));

    MobilityHelper ueMobility;

    ueMobility.SetMobilityModel(
        "ns3::ConstantVelocityMobilityModel");

    ueMobility.SetPositionAllocator(uePos);
    ueMobility.Install(ueNodes);

    Ptr<ConstantVelocityMobilityModel> movingUe =
        ueNodes.Get(0)->GetObject<ConstantVelocityMobilityModel>();

    movingUe->SetVelocity(Vector(ueSpeed, 0.0, 0.0));

    // Phase B1: one shared 3.5 GHz, 20 MHz BWP with an urban macro channel.
    auto epcHelper = CreateObject<NrPointToPointEpcHelper>();
    auto nrHelper = CreateObject<NrHelper>();
    auto beamformingHelper = CreateObject<IdealBeamformingHelper>();
    beamformingHelper->SetAttribute("BeamformingMethod",
                                   TypeIdValue(DirectPathBeamforming::GetTypeId()));
    nrHelper->SetEpcHelper(epcHelper);
    nrHelper->SetBeamformingHelper(beamformingHelper);
    if (enableHandover)
    {
        nrHelper->SetAttribute("UseIdealRrc", BooleanValue(false));
        nrHelper->SetHandoverAlgorithmType("ns3::NrA3RsrpHandoverAlgorithm");
        nrHelper->SetHandoverAlgorithmAttribute("Hysteresis", DoubleValue(1.5));
        nrHelper->SetHandoverAlgorithmAttribute("TimeToTrigger", TimeValue(MilliSeconds(128)));
    }
    auto [bandwidth, bwps] = nrHelper->CreateBandwidthParts(
        {CcBwpCreator::SimpleOperationBandConf(3.5e9, 20e6, 1)}, "UMa");
    NetDeviceContainer gnbDevices = nrHelper->InstallGnbDevice(gnbNodes, bwps);
    NetDeviceContainer ueDevices = nrHelper->InstallUeDevice(ueNodes, bwps);
    for (uint32_t i = 0; i < gnbDevices.GetN(); ++i)
    {
        NrHelper::GetGnbPhy(gnbDevices.Get(i), 0)->SetAttribute("Numerology", UintegerValue(1));
        NrHelper::GetGnbPhy(gnbDevices.Get(i), 0)->SetTxPower(43.0);
        DynamicCast<NrGnbNetDevice>(gnbDevices.Get(i))->ConfigureCell();
    }

    InternetStackHelper internet;
    internet.Install(ueNodes);
    // The installed EPC helper also installs the UE IPv4 default route.
    Ipv4InterfaceContainer ueInterfaces = epcHelper->AssignUeIpv4Address(ueDevices);
    auto ueDevice = DynamicCast<NrUeNetDevice>(ueDevices.Get(0));
    RadioMeasurementLogger radioLogger(outputDir + "/radio_measurements.csv");
    for (uint32_t i = 0; i < ueDevices.GetN(); ++i)
    {
        auto device = DynamicCast<NrUeNetDevice>(ueDevices.Get(i));
        for (uint32_t bwp = 0; bwp < bwps.size(); ++bwp)
        {
            auto callback = MakeCallback(&RadioMeasurementLogger::Record, &radioLogger)
                                .Bind(device, i);
            NS_ABORT_MSG_IF(!NrHelper::GetUePhy(device, bwp)->TraceConnectWithoutContext(
                                "ReportUeMeasurements", callback),
                            "Cannot connect passive radio measurement trace");
        }
    }
    auto gnb0Device = DynamicCast<NrGnbNetDevice>(gnbDevices.Get(0));
    auto gnb1Device = DynamicCast<NrGnbNetDevice>(gnbDevices.Get(1));
    HandoverLogger handover(outputDir, gnb0Device->GetCellId(), gnb1Device->GetCellId());
    if (enableHandover)
    {
        nrHelper->AddX2Interface(gnbNodes);
        NS_ABORT_MSG_IF(!ueDevice->GetRrc()->TraceConnectWithoutContext(
                            "HandoverStart", MakeCallback(&HandoverLogger::Start, &handover)) ||
                            !ueDevice->GetRrc()->TraceConnectWithoutContext(
                            "HandoverEndOk", MakeCallback(&HandoverLogger::End, &handover)) ||
                            !ueDevice->GetRrc()->TraceConnectWithoutContext(
                            "HandoverEndError", MakeCallback(&HandoverLogger::Error, &handover)) ||
                            !gnb1Device->GetRrc()->TraceConnectWithoutContext(
                            "HandoverEndOk", MakeCallback(&HandoverLogger::GnbEnd, &handover)),
                        "Cannot connect handover traces");
        for (auto device = gnbDevices.Begin(); device != gnbDevices.End(); ++device)
        {
            NS_ABORT_MSG_IF(!DynamicCast<NrGnbNetDevice>(*device)->GetRrc()->TraceConnectWithoutContext(
                                "RecvMeasurementReport",
                                MakeCallback(&HandoverLogger::Measurement, &handover)),
                            "Cannot connect RRC measurement trace");
        }
        std::cout << "B3 configuration: A3-RSRP hysteresis_dB=1.5 TTT_ms=128 X2=enabled"
                     " UseIdealRrc=false simTime_s=" << simTime << '\n';
    }
    AttachmentRecord attachment;
    NS_ABORT_MSG_IF(!ueDevice->GetRrc()->TraceConnectWithoutContext(
                        "ConnectionEstablished", MakeBoundCallback(&RecordAttachment, &attachment)),
                    "Cannot connect UE RRC attachment trace");
    // Both cells are configured; explicitly select gNB 0 for the initial attachment.
    nrHelper->AttachToGnb(ueDevices.Get(0), gnbDevices.Get(0));
    std::cout << "NR setup: gNBs=" << gnbDevices.GetN() << " UEs=" << ueDevices.GetN()
              << " bandwidth_Hz=" << bandwidth << " target_gNB=0 cellId="
              << gnb0Device->GetCellId() << " UE_IP=" << ueInterfaces.GetAddress(0)
              << " gateway=" << epcHelper->GetUeDefaultGatewayAddress() << '\n';

    // CSV logging
    const Time interval = MilliSeconds(samplingMs);
    const Time stopTime = Seconds(simTime);

    // SetupRemoteHost installs the host stack, PGW link and route to 7.0.0.0/8.
    auto [remoteHost, remoteAddress] = epcHelper->SetupRemoteHost("100Mb/s", 1500,
                                                              MilliSeconds(1));
    const Time trafficStart = Seconds(1);
    const Time trafficEnd = stopTime - Seconds(1);
    const uint16_t udpPort = 1234;
    UdpServerHelper receiverHelper(udpPort);
    ApplicationContainer receiverApps = receiverHelper.Install(ueNodes.Get(0));
    receiverApps.Start(Seconds(0));
    // Leave the receiver active through the last mobility/traffic measurement.
    receiverApps.Stop(stopTime + NanoSeconds(1));

    Simulator::Schedule(trafficStart, [ueDevice, gnb0Device, &attachment]() {
        NS_ABORT_MSG_IF(attachment.count != 1 ||
                            ueDevice->GetRrc()->GetState() != NrUeRrc::CONNECTED_NORMALLY ||
                            ueDevice->GetRrc()->GetCellId() != gnb0Device->GetCellId(),
                        "UDP traffic requires completed attachment to gNB 0");
    });
    UdpClientHelper senderHelper(InetSocketAddress(ueInterfaces.GetAddress(0), udpPort));
    senderHelper.SetAttribute("PacketSize", UintegerValue(UdpTrafficLogger::PACKET_SIZE));
    senderHelper.SetAttribute("Interval", TimeValue(MilliSeconds(10)));
    senderHelper.SetAttribute("MaxPackets", UintegerValue(0)); // Continuous until trafficEnd.
    ApplicationContainer senderApps = senderHelper.Install(remoteHost);
    senderApps.Start(trafficStart);
    senderApps.Stop(trafficEnd);
    auto sender = DynamicCast<UdpClient>(senderApps.Get(0));
    auto receiver = DynamicCast<UdpServer>(receiverApps.Get(0));
    UdpTrafficLogger trafficLogger(sender, trafficStart, trafficEnd, stopTime,
                                   outputDir + "/udp_traffic.csv", outputDir + "/udp_packets.csv");
    NS_ABORT_MSG_IF(!receiver->TraceConnectWithoutContext(
                        "RxWithoutAddress", MakeCallback(&UdpTrafficLogger::Receive, &trafficLogger)),
                    "Cannot connect UDP receiver trace");
    trafficLogger.Start();
    std::cout << "UDP setup: remote_host=" << remoteAddress << " destination="
              << ueInterfaces.GetAddress(0) << ':' << udpPort
              << " packet_bytes=512 interval_ms=10 start_s=" << trafficStart.GetSeconds()
              << " end_s=" << trafficEnd.GetSeconds() << " outputDir=" << outputDir << '\n';

    UeMobilityLogger logger(
        ueNodes,
        interval,        stopTime,
        outputDir + "/ue_mobility.csv");

    logger.Start();

    Simulator::Stop(stopTime+NanoSeconds(1));
    Simulator::Run();

    logger.Close();
    trafficLogger.Close();
    handover.Close();
    radioLogger.Close();

    // Validation
    const auto& samples = logger.GetSamples();

    bool ok = true;

    auto fail = [&ok](const std::string& msg)
    {
        std::cerr << "VALIDATION FAIL: "
                  << msg << std::endl;
        ok = false;
    };

    const int64_t intervalNs = interval.GetNanoSeconds();

    const int64_t expectedCount =
        stopTime.GetNanoSeconds() / intervalNs + 1;

    if (static_cast<int64_t>(samples.size()) != expectedCount)
    {
        fail("sample count " +
             std::to_string(samples.size()) +
             " != expected " +
             std::to_string(expectedCount));
    }

    double maxPosErr = 0.0;
    double maxSpeedErr = 0.0;

    for (size_t k = 0; k < samples.size(); ++k)
    {
        const auto& s = samples[k];

        if (s.timeNs != static_cast<int64_t>(k) * intervalNs)
        {
            fail("timestamp of sample " +
                 std::to_string(k) +
                 " is not k * interval");
            break;
        }

        const double t =
            static_cast<double>(s.timeNs) * 1e-9;

        const double ex = ueStartX + ueSpeed * t;
        const double ey = ueOffsetY;
        const double ez = ueHeight;

        const double err =
            std::sqrt(
                (s.position.x - ex) * (s.position.x - ex) +
                (s.position.y - ey) * (s.position.y - ey) +
                (s.position.z - ez) * (s.position.z - ez));

        maxPosErr = std::max(maxPosErr, err);

        maxSpeedErr = std::max(
            maxSpeedErr,
            std::abs(s.speed - ueSpeed));
    }

    if (maxPosErr > 1e-6)
    {
        fail("max position error " +
             std::to_string(maxPosErr) +
             " m exceeds 1e-6 m");
    }

    if (maxSpeedErr > 1e-9)
    {
        fail("max speed error " +
             std::to_string(maxSpeedErr) +
             " m/s exceeds 1e-9 m/s");
    }

    if (!samples.empty())
    {
        const Vector& last = samples.back().position;

        const double moved = last.x - ueStartX;

        const double expectedMoved =
            ueSpeed *
            (static_cast<double>(samples.back().timeNs) * 1e-9);

        if (std::abs(moved - expectedMoved) > 1e-6)
        {
            fail("net displacement mismatch");
        }

        Ptr<MobilityModel> g0 =
            gnbNodes.Get(0)->GetObject<MobilityModel>();

        Ptr<MobilityModel> g1 =
            gnbNodes.Get(1)->GetObject<MobilityModel>();

        Ptr<MobilityModel> ue =
            ueNodes.Get(0)->GetObject<MobilityModel>();

        std::cout
            << "Info: final UE x = "
            << last.x
            << " m; distance to gNB0 = "
            << ue->GetDistanceFrom(g0)
            << " m, to gNB1 = "
            << ue->GetDistanceFrom(g1)
            << " m"
            << std::endl;

        if (last.x > gnbSeparation)
        {
            std::cout
                << "Warning: UE passes gNB 1 before "
                << "the end of the simulation."
                << std::endl;
        }
    }

    std::cout
        << "Samples written: "
        << samples.size()
        << " (expected "
        << expectedCount
        << ")\n"
        << "Max position error [m]: "
        << maxPosErr
        << "\n"
        << "Max speed error [m/s]: "
        << maxSpeedErr
        << "\n"
        << "PHASE A VALIDATION: "
        << (ok ? "PASS" : "FAIL")
        << std::endl;

    const auto rrc = ueDevice->GetRrc();
    const bool attachmentOk = attachment.count == 1 &&
                              attachment.imsi == ueDevice->GetImsi() &&
                              attachment.cellId == gnb0Device->GetCellId() &&
                              attachment.rnti != 0 &&
                              (enableHandover || (attachment.rnti == rrc->GetRnti() &&
                               rrc->GetCellId() == gnb0Device->GetCellId())) &&
                              rrc->GetState() == NrUeRrc::CONNECTED_NORMALLY &&
                              ueInterfaces.GetAddress(0) != Ipv4Address::GetAny();
    std::cout << "NR final: cellId=" << rrc->GetCellId() << " RNTI=" << rrc->GetRnti()
              << " CONNECTED_NORMALLY=" << (rrc->GetState() == NrUeRrc::CONNECTED_NORMALLY)
              << " connection_events=" << attachment.count << '\n'
              << "PHASE B1 VALIDATION: " << (attachmentOk ? "PASS" : "FAIL") << std::endl;

    const uint64_t txPackets = trafficLogger.GetTxPackets();
    const uint64_t rxPackets = trafficLogger.GetRxPackets();
    const uint64_t rxBytes = trafficLogger.GetRxBytes();
    const int64_t packetIntervalNs = MilliSeconds(10).GetNanoSeconds();
    const uint64_t expectedTx = ((trafficEnd - trafficStart).GetNanoSeconds() + packetIntervalNs - 1) /
                               packetIntervalNs;
    const bool trafficOk = txPackets == expectedTx && rxPackets > 0 &&
                           rxPackets <= txPackets && rxPackets == receiver->GetReceived() &&
                           rxBytes == rxPackets * UdpTrafficLogger::PACKET_SIZE &&
                           sender->GetTotalTx() == txPackets * UdpTrafficLogger::PACKET_SIZE;
    std::cout << "UDP measured: tx_packets=" << txPackets << " rx_packets=" << rxPackets
              << " rx_bytes=" << rxBytes << " undelivered_packets=" << (txPackets - rxPackets)
              << " pdr=" << trafficLogger.GetPdr()
              << " average_throughput_mbps=" << trafficLogger.GetThroughput()
              << " averaging_window_s=" << (trafficEnd - trafficStart).GetSeconds() << '\n'
              << "PHASE B2 VALIDATION: " << (trafficOk ? "PASS" : "FAIL") << std::endl;

    const bool handoverOk = handover.starts == 1 && handover.ends == 1 &&
                            handover.gnbEnds == 1 && handover.errors == 0 && handover.consistent &&
                            handover.sourceToTargetReports > 0 &&
                            handover.lastSourceReport <= handover.startTime &&
                            handover.reportImsi == ueDevice->GetImsi() &&
                            handover.ueImsi == ueDevice->GetImsi() &&
                            handover.sourceCell == gnb0Device->GetCellId() &&
                            handover.targetCell == gnb1Device->GetCellId() &&
                            handover.endCell == rrc->GetCellId() &&
                            handover.endRnti == rrc->GetRnti() &&
                            rrc->GetCellId() == gnb1Device->GetCellId() &&
                            rrc->GetState() == NrUeRrc::CONNECTED_NORMALLY &&
                            gnb1Device->GetRrc()->GetUeManager(rrc->GetRnti())->GetState() ==
                                NrUeManager::CONNECTED_NORMALLY &&
                            gnb1Device->GetRrc()->GetUeManager(rrc->GetRnti())->GetImsi() ==
                                ueDevice->GetImsi() &&
                            handover.startTime >= trafficStart && handover.endTime >= handover.startTime &&
                            handover.endTime < trafficEnd && trafficLogger.GetLastRx() > handover.endTime;
    std::cout << "B3 observed: starts=" << handover.starts << " UE_ends=" << handover.ends
              << " target_gNB_ends=" << handover.gnbEnds << " errors=" << handover.errors
              << " measurement_reports=" << handover.reports << " final_cell=" << rrc->GetCellId()
              << " last_udp_rx_s=" << trafficLogger.GetLastRx().GetSeconds() << '\n'
              << "PHASE B3 VALIDATION: "
              << (enableHandover ? (handoverOk ? "PASS" : "FAIL") : "NOT VERIFIED (disabled)")
              << std::endl;

    Simulator::Destroy();

    return (ok && attachmentOk && trafficOk && (!enableHandover || handoverOk)) ? 0 : 1;
}
