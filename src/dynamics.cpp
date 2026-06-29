#include "flight_sim/dynamics.hpp"

namespace flight_sim {

QuadrotorDynamics::QuadrotorDynamics(SimulationConfig config) : config_(config) {}

void QuadrotorDynamics::reset(DroneState initial) {
    state_ = initial;
    state_.attitude.normalize();
}

void QuadrotorDynamics::step(const ControlCommand& command) {
    const double dt = config_.dt_s;
    const Mat3 r = state_.attitude.toRotationMatrix();
    const Vec3 gravity{0.0, 0.0, -config_.gravity_mps2};
    const Vec3 thrust_body{0.0, 0.0, command.thrust_n};
    const Vec3 drag = state_.velocity_mps * (-config_.linear_drag);
    const Vec3 accel = (r * thrust_body + drag) / config_.mass_kg + gravity;

    state_.velocity_mps += accel * dt;
    state_.position_m += state_.velocity_mps * dt;

    const Vec3 i = config_.inertia_kgm2;
    const Vec3 iw{i.x * state_.omega_radps.x, i.y * state_.omega_radps.y, i.z * state_.omega_radps.z};
    const Vec3 coriolis = cross(state_.omega_radps, iw);
    const Vec3 omega_dot{
        (command.moment_nm.x - coriolis.x) / i.x,
        (command.moment_nm.y - coriolis.y) / i.y,
        (command.moment_nm.z - coriolis.z) / i.z,
    };

    state_.omega_radps += omega_dot * dt;
    state_.attitude.integrateBodyRate(state_.omega_radps, dt);
}

} // namespace flight_sim

