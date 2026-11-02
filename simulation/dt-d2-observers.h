// SPDX-License-Identifier: GPL-2.0-only
// Passive PHY observers derived from the preserved D1 implementation.
#ifndef DT_D2_OBSERVERS_H
#define DT_D2_OBSERVERS_H
namespace d2
{
/** Passively log the native DATA and CONTROL PHY SINR traces. */
class SinrMeasurementLogger
{
  public:
    /**
     * Open the separate SINR CSV stream.
     * @param path New output file path.
     */
    explicit SinrMeasurementLogger(const std::string& path)
        : m_out(path)
    {
        NS_ABORT_MSG_IF(!m_out, "Cannot open " << path);
        m_out << "time_ns,time_s,ue_id,imsi,rnti,cell_id,bwp_id,channel_type,"
                 "sinr_linear,sinr_db,valid,status,source\n";
    }

    /**
     * Observe a native PHY SINR event without changing simulator state.
     * @param ue Bound UE device, used only to read its full-width IMSI.
     * @param ueId Bound mobility CSV UE index.
     * @param channel Bound DATA or CONTROL channel label.
     * @param cellId Current cell identity provided by the trace.
     * @param rnti RNTI provided by the trace.
     * @param linear Native SINR power ratio, before logarithmic conversion.
     * @param bwpId BWP identity provided by the trace.
     */
    void Record(Ptr<NrUeNetDevice> ue, uint32_t ueId, std::string channel,
                uint16_t cellId, uint16_t rnti, double linear, uint16_t bwpId)
    {
        const char* status = !std::isfinite(linear) ? "nonfinite" :
                             linear <= 0 ? "not_positive" :
                             linear == std::numeric_limits<double>::max() ?
                                 "empty_spectrum_sentinel" : "ok";
        const bool valid = std::string(status) == "ok";
        const Time now = Simulator::Now();
        m_out << now.GetNanoSeconds() << ',' << std::fixed << std::setprecision(9)
              << now.GetSeconds() << ',' << ueId << ',' << ue->GetImsi() << ','
              << rnti << ',' << cellId << ',' << bwpId << ',' << channel << ','
              << std::scientific << std::setprecision(17) << linear << ',';
        if (valid)
        {
            m_out << 10.0 * std::log10(linear);
        }
        m_out << ',' << valid << ',' << status << ",NrUePhy::"
              << (channel == "DL_DATA" ? "DlDataSinr" : "DlCtrlSinr") << '\n';
    }

    /** Close and check the output stream. */
    void Close()
    {
        m_out.close();
        NS_ABORT_MSG_IF(m_out.fail(), "SINR CSV write failed");
    }

  private:
    std::ofstream m_out; ///< Separate passive SINR event CSV.
};

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

}
#endif
