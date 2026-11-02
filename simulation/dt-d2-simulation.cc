// SPDX-License-Identifier: GPL-2.0-only
// Independent D2 executable. D1 sources and selectors are intentionally untouched.
#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/nr-module.h"
#include "ns3/antenna-module.h"
#include "ns3/propagation-module.h"
#include "ns3/spectrum-module.h"
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <vector>
using namespace ns3;
#include "dt-d2-observers.h"
#include "dt-d2-support.h"

/**
 * Run the independent D2 foundation scenario.
 * @param argc Argument count.
 * @param argv Argument strings.
 * @return Producer checks status; the offline gate must also pass.
 */
int main(int argc, char* argv[])
{
    double duration=90, turn=40;
    uint32_t samplingMs=30, seed=1, run=1;
    std::string output="dt-output/d2";
    CommandLine cmd(__FILE__);
    cmd.AddValue("simTime","Observation duration [s]",duration);
    cmd.AddValue("turnTime","Reverse at this time and stop at twice this time [s]",turn);
    cmd.AddValue("samplingMs","Mobility and RRC sample step [ms]",samplingMs);
    cmd.AddValue("seed","RNG seed",seed);
    cmd.AddValue("run","RNG run",run);
    cmd.AddValue("outputDir","Fresh D2 output directory",output);
    cmd.Parse(argc,argv);
    return d2::Run(duration,samplingMs,seed,run,true,turn,output);
}
