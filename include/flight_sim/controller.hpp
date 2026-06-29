#pragma once

#include "flight_sim/state.hpp"

namespace flight_sim {

class CascadedController {
public:
    explicit CascadedController(SimulationConfig config);

    ControlCommand update(const TrajectorySetpoint& ref, const NavEstimate& estimate);

private:
    SimulationConfig config_;
    Vec3 kp_pos_{3.2, 3.2, 5.0};
    Vec3 kd_pos_{2.6, 2.6, 3.2};
    Vec3 kp_att_{0.075, 0.075, 0.045};
    Vec3 kd_att_{0.018, 0.018, 0.012};
    double max_horizontal_accel_mps2_{3.0};
    double max_vertical_accel_mps2_{8.0};
    double max_tilt_rad_{25.0 * kPi / 180.0};
    double min_thrust_n_{0.0};
    double max_thrust_n_{22.0};
    Vec3 max_moment_nm_{0.12, 0.12, 0.08};

    Quaternion desiredAttitudeFromAccel(const Vec3& accel_cmd, double yaw_rad) const;
};

} // namespace flight_sim
