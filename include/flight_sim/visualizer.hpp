#pragma once

#include "flight_sim/flight_state_machine.hpp"
#include "flight_sim/state.hpp"

#include <string>
#include <vector>

namespace flight_sim {

class HtmlVisualizer {
public:
    void addSample(
        double t_s,
        const DroneState& truth,
        const NavEstimate& nav,
        const SensorSample& sensor,
        const TrajectorySetpoint& ref,
        const DetectionState& detection,
        const ModeDecision& mode);

    bool writeHtml(const std::string& path, const SimulationConfig& config) const;

private:
    struct Sample {
        double t_s{};
        Vec3 truth{};
        Vec3 estimate{};
        Vec3 gps{};
        Vec3 uwb{};
        Vec3 ref{};
        bool attack{};
        bool detected{};
        bool gps_trusted{};
        bool uwb_valid{};
        bool optical_flow_valid{};
        bool magnetometer_valid{};
        double pseudorange_residual_rms{};
        double pseudorange_residual_max_abs{};
        double glrt_statistic{};
        double glrt_threshold{};
        bool glrt_detected{};
        std::string mode;
    };

    std::vector<Sample> samples_;
};

} // namespace flight_sim
