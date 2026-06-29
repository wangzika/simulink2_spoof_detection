#pragma once

#include "flight_sim/inav_parameters.hpp"
#include "flight_sim/state.hpp"

#include <string>

namespace flight_sim {

enum class FlightMode {
    Grounded,
    Takeoff,
    Mission,
    GpsSuspect,
    GpsRejected,
    GpsReacquire,
    Landing,
};

struct ModeDecision {
    FlightMode mode{FlightMode::Grounded};
    bool gps_trusted{true};
    bool failsafe{false};
    std::string mode_name{"Grounded"};
};

class FlightStateMachine {
public:
    FlightStateMachine(InavParameters params, SimulationConfig config = {});

    ModeDecision update(double t_s, const SensorSample& sensor, const DetectionState& detection);
    const ModeDecision& decision() const { return decision_; }

private:
    InavParameters params_;
    SimulationConfig config_;
    ModeDecision decision_{};
    double mode_enter_time_s_{0.0};
    double last_detection_time_s_{-1e9};

    void setMode(FlightMode mode, double t_s);
    static std::string modeName(FlightMode mode);
};

} // namespace flight_sim
