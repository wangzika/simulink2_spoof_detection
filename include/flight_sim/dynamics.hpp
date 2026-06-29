#pragma once

#include "flight_sim/state.hpp"

namespace flight_sim {

class QuadrotorDynamics {
public:
    explicit QuadrotorDynamics(SimulationConfig config);

    void reset(DroneState initial = {});
    void step(const ControlCommand& command);

    const DroneState& state() const { return state_; }

private:
    SimulationConfig config_;
    DroneState state_{};
};

} // namespace flight_sim

