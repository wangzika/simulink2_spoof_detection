#include "flight_sim/controller.hpp"

#include <cmath>

namespace flight_sim {

CascadedController::CascadedController(SimulationConfig config) : config_(config) {
    max_thrust_n_ = 2.7 * config_.mass_kg * config_.gravity_mps2;
}

ControlCommand CascadedController::update(const TrajectorySetpoint& ref, const NavEstimate& estimate) {
    ControlCommand command;
    const Vec3 pos_error = ref.position_m - estimate.position_m;
    const Vec3 vel_error = ref.velocity_mps - estimate.velocity_mps;

    const Vec3 raw_accel_cmd{
        kp_pos_.x * pos_error.x + kd_pos_.x * vel_error.x + ref.acceleration_mps2.x,
        kp_pos_.y * pos_error.y + kd_pos_.y * vel_error.y + ref.acceleration_mps2.y,
        kp_pos_.z * pos_error.z + kd_pos_.z * vel_error.z + ref.acceleration_mps2.z,
    };
    const Vec3 horizontal_accel =
        clampNorm(Vec3{raw_accel_cmd.x, raw_accel_cmd.y, 0.0}, max_horizontal_accel_mps2_);
    Vec3 accel_cmd{
        horizontal_accel.x,
        horizontal_accel.y,
        clamp(raw_accel_cmd.z, -max_vertical_accel_mps2_, max_vertical_accel_mps2_),
    };
    command.desired_accel_mps2 = accel_cmd;
    command.desired_attitude = desiredAttitudeFromAccel(accel_cmd, ref.yaw_rad);

    const Vec3 desired_force_world = config_.mass_kg * (accel_cmd + Vec3{0.0, 0.0, config_.gravity_mps2});
    const Mat3 current_r = estimate.attitude.toRotationMatrix();
    const Vec3 body_z = current_r.col(2);
    command.thrust_n = clamp(dot(desired_force_world, body_z), min_thrust_n_, max_thrust_n_);

    const Quaternion current_conjugate{
        estimate.attitude.w,
        -estimate.attitude.x,
        -estimate.attitude.y,
        -estimate.attitude.z,
    };
    Quaternion attitude_delta = current_conjugate * command.desired_attitude;
    attitude_delta.normalize();
    if (attitude_delta.w < 0.0) {
        attitude_delta = attitude_delta * -1.0;
    }
    const Vec3 attitude_error{
        2.0 * attitude_delta.x,
        2.0 * attitude_delta.y,
        2.0 * attitude_delta.z,
    };

    Vec3 moment{
        kp_att_.x * attitude_error.x - kd_att_.x * estimate.omega_radps.x,
        kp_att_.y * attitude_error.y - kd_att_.y * estimate.omega_radps.y,
        kp_att_.z * attitude_error.z - kd_att_.z * estimate.omega_radps.z,
    };
    moment.x = clamp(moment.x, -max_moment_nm_.x, max_moment_nm_.x);
    moment.y = clamp(moment.y, -max_moment_nm_.y, max_moment_nm_.y);
    moment.z = clamp(moment.z, -max_moment_nm_.z, max_moment_nm_.z);
    command.moment_nm = moment;

    return command;
}

Quaternion CascadedController::desiredAttitudeFromAccel(const Vec3& accel_cmd, double yaw_rad) const {
    Vec3 desired_z = (accel_cmd + Vec3{0.0, 0.0, config_.gravity_mps2}).normalized();
    const double max_xy = std::tan(max_tilt_rad_) * std::max(0.2, desired_z.z);
    desired_z.x = clamp(desired_z.x, -max_xy, max_xy);
    desired_z.y = clamp(desired_z.y, -max_xy, max_xy);
    desired_z = desired_z.normalized();

    const Vec3 yaw_x{std::cos(yaw_rad), std::sin(yaw_rad), 0.0};
    Vec3 desired_y = cross(desired_z, yaw_x).normalized();
    if (desired_y.norm() < 1e-6) {
        desired_y = {0.0, 1.0, 0.0};
    }
    Vec3 desired_x = cross(desired_y, desired_z).normalized();
    const Mat3 desired_r = Mat3::fromColumns(desired_x, desired_y, desired_z);
    return Quaternion::fromRotationMatrix(desired_r);
}

} // namespace flight_sim
