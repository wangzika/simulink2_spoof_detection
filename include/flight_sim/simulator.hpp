#pragma once

#include "flight_sim/controller.hpp"
#include "flight_sim/detector.hpp"
#include "flight_sim/dynamics.hpp"
#include "flight_sim/flight_state_machine.hpp"
#include "flight_sim/inav_parameters.hpp"
#include "flight_sim/navigation.hpp"
#include "flight_sim/sensors.hpp"
#include "flight_sim/trajectory.hpp"
#include "flight_sim/visualizer.hpp"

#include <fstream>

namespace flight_sim {

class Simulator {
public:
    Simulator(SimulationConfig sim_config, AttackConfig attack_config, DetectorConfig detector_config);

    int run();

private:
    SimulationConfig sim_config_;
    AttackConfig attack_config_;
    DetectorConfig detector_config_;
    InavParameters inav_params_;

    QuadrotorDynamics dynamics_;
    SensorModel sensors_;
    MultiSensorNavigation navigation_;
    CascadedController controller_;
    GpsSpoofDetector detector_;
    FlightStateMachine state_machine_;
    TrajectoryPlanner trajectory_;
    HtmlVisualizer visualizer_;

    void writeHeader(std::ofstream& out);
    void writeSample(
        std::ofstream& out,
        double t_s,
        const DroneState& truth,
        const NavEstimate& nav,
        const SensorSample& sensor,
        const TrajectorySetpoint& ref,
        const ControlCommand& command,
        const DetectionState& detection,
        const ModeDecision& mode);
};

} // namespace flight_sim
