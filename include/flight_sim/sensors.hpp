#pragma once

#include "flight_sim/gnss.hpp"
#include "flight_sim/state.hpp"

#include <random>
#include <vector>

namespace flight_sim {

class SensorModel {
public:
    SensorModel(SimulationConfig config, AttackConfig attack);

    SensorSample sample(double t_s, const DroneState& truth, const ControlCommand& last_command);

private:
    SimulationConfig config_;
    AttackConfig attack_;
    std::mt19937 rng_{7};
    std::normal_distribution<double> unit_noise_{0.0, 1.0};
    double gps_period_s_{0.05};
    double uwb_period_s_{0.10};
    double optical_flow_period_s_{0.02};
    double magnetometer_period_s_{0.04};
    double next_gps_time_s_{0.0};
    double next_uwb_time_s_{0.0};
    double next_optical_flow_time_s_{0.0};
    double next_magnetometer_time_s_{0.0};
    Vec3 last_gps_position_{};
    Vec3 last_gps_velocity_{};
    Vec3 last_uwb_position_{};
    Vec3 last_optical_flow_velocity_{};
    double last_magnetometer_yaw_rad_{0.0};
    Vec3 last_receiver_ecef_{};
    std::vector<Ephemeris> ephemerides_;
    std::vector<PseudorangeMeasurement> last_pseudoranges_;
    GeodeticPosition reference_{};

    double noise(double sigma);
    Vec3 noise3(double sigma);
    double attackScale(double t_s) const;
    Vec3 attackOffset(double t_s) const;
    std::vector<PseudorangeMeasurement> simulatePseudoranges(
        double t_s,
        const DroneState& truth,
        bool attacked);
};

} // namespace flight_sim
