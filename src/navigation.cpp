#include "flight_sim/navigation.hpp"

#include <algorithm>
#include <cmath>

namespace flight_sim {

namespace {

double wrapPi(double angle_rad) {
    while (angle_rad > kPi) {
        angle_rad -= 2.0 * kPi;
    }
    while (angle_rad < -kPi) {
        angle_rad += 2.0 * kPi;
    }
    return angle_rad;
}

} // namespace

MultiSensorNavigation::MultiSensorNavigation(SimulationConfig config, InavParameters params)
    : config_(config), params_(params) {}

void MultiSensorNavigation::reset(const DroneState& initial) {
    estimate_.position_m = initial.position_m;
    estimate_.velocity_mps = initial.velocity_mps;
    estimate_.attitude = initial.attitude;
    estimate_.omega_radps = initial.omega_radps;
    estimate_.accel_bias_mps2 = {};
    axis_[0].reset(initial.position_m.x, initial.velocity_mps.x);
    axis_[1].reset(initial.position_m.y, initial.velocity_mps.y);
    axis_[2].reset(initial.position_m.z, initial.velocity_mps.z);
    initialized_ = false;
    last_time_s_ = 0.0;
}

void MultiSensorNavigation::propagate(const SensorSample& sample) {
    if (!initialized_) {
        initialized_ = true;
        last_time_s_ = sample.t_s;
    }
    const double dt = std::max(1e-6, sample.t_s - last_time_s_);
    last_time_s_ = sample.t_s;

    estimate_.omega_radps = sample.gyro_radps;
    estimate_.attitude.integrateBodyRate(sample.gyro_radps, dt);

    const Mat3 r = estimate_.attitude.toRotationMatrix();
    const Vec3 gravity{0.0, 0.0, -config_.gravity_mps2};
    const Vec3 accel_world = r * sample.accel_body_mps2 + gravity;
    axis_[0].predict(accel_world.x, dt, params_.PARAM_INAV_ACC_NOISE, params_.PARAM_INAV_W_ACC_BIAS);
    axis_[1].predict(accel_world.y, dt, params_.PARAM_INAV_ACC_NOISE, params_.PARAM_INAV_W_ACC_BIAS);
    axis_[2].predict(accel_world.z, dt, params_.PARAM_INAV_ACC_NOISE, params_.PARAM_INAV_W_ACC_BIAS);
    syncEstimateFromFilter();
}

void MultiSensorNavigation::correct(const SensorSample& sample, bool gps_trusted) {
    if (sample.gps_valid && gps_trusted) {
        const double gps_pos_var = params_.PARAM_INAV_GPS_P_NOISE * params_.PARAM_INAV_GPS_P_NOISE;
        const double gps_vel_var = params_.PARAM_INAV_GPS_V_NOISE * params_.PARAM_INAV_GPS_V_NOISE;

        axis_[0].updatePosition(sample.gps_position_m.x, gps_pos_var, params_.PARAM_INAV_W_XY_GPS_P);
        axis_[1].updatePosition(sample.gps_position_m.y, gps_pos_var, params_.PARAM_INAV_W_XY_GPS_P);
        axis_[2].updatePosition(sample.gps_position_m.z, gps_pos_var, params_.PARAM_INAV_W_Z_GPS_P);

        axis_[0].updateVelocity(sample.gps_velocity_mps.x, gps_vel_var, params_.PARAM_INAV_W_XY_GPS_V);
        axis_[1].updateVelocity(sample.gps_velocity_mps.y, gps_vel_var, params_.PARAM_INAV_W_XY_GPS_V);
        axis_[2].updateVelocity(sample.gps_velocity_mps.z, gps_vel_var, params_.PARAM_INAV_W_XY_GPS_V);
    }

    if (sample.uwb_valid) {
        const double uwb_pos_var = params_.PARAM_INAV_UWB_P_NOISE * params_.PARAM_INAV_UWB_P_NOISE;
        axis_[0].updatePosition(sample.uwb_position_m.x, uwb_pos_var, params_.PARAM_INAV_W_XY_UWB_P);
        axis_[1].updatePosition(sample.uwb_position_m.y, uwb_pos_var, params_.PARAM_INAV_W_XY_UWB_P);
        axis_[2].updatePosition(sample.uwb_position_m.z, uwb_pos_var, params_.PARAM_INAV_W_Z_UWB_P);
    }

    if (sample.optical_flow_valid) {
        const double flow_vel_var = params_.PARAM_INAV_FLOW_V_NOISE * params_.PARAM_INAV_FLOW_V_NOISE;
        axis_[0].updateVelocity(sample.optical_flow_velocity_mps.x, flow_vel_var, params_.PARAM_INAV_W_XY_FLOW_V);
        axis_[1].updateVelocity(sample.optical_flow_velocity_mps.y, flow_vel_var, params_.PARAM_INAV_W_XY_FLOW_V);
    }

    const double baro_var = params_.PARAM_INAV_BARO_NOISE * params_.PARAM_INAV_BARO_NOISE;
    axis_[2].updatePosition(sample.baro_altitude_m, baro_var, params_.PARAM_INAV_W_Z_BARO_P);
    syncEstimateFromFilter();

    if (sample.magnetometer_valid && params_.PARAM_INAV_W_YAW_MAG > 0.0) {
        const double yaw_error = wrapPi(sample.magnetometer_yaw_rad - estimate_.attitude.yawRad());
        const double gain = clamp(
            params_.PARAM_INAV_W_YAW_MAG /
                std::max(params_.PARAM_INAV_MAG_YAW_NOISE * params_.PARAM_INAV_MAG_YAW_NOISE, 1e-6),
            0.0,
            0.35);
        const Quaternion correction = Quaternion::fromYaw(clamp(gain * yaw_error, -0.12, 0.12));
        estimate_.attitude = correction * estimate_.attitude;
        estimate_.attitude.normalize();
    }
}

void MultiSensorNavigation::syncEstimateFromFilter() {
    estimate_.position_m = {axis_[0].pos, axis_[1].pos, axis_[2].pos};
    estimate_.velocity_mps = {axis_[0].vel, axis_[1].vel, axis_[2].vel};
    estimate_.accel_bias_mps2 = {axis_[0].bias, axis_[1].bias, axis_[2].bias};
}

void MultiSensorNavigation::AxisKalman::reset(double pos0, double vel0) {
    pos = pos0;
    vel = vel0;
    bias = 0.0;
    p[0][0] = 0.35;
    p[0][1] = 0.0;
    p[0][2] = 0.0;
    p[1][0] = 0.0;
    p[1][1] = 0.35;
    p[1][2] = 0.0;
    p[2][0] = 0.0;
    p[2][1] = 0.0;
    p[2][2] = 0.05;
}

void MultiSensorNavigation::AxisKalman::predict(double accel_meas, double dt, double accel_noise, double bias_noise) {
    const double corrected_accel = accel_meas - bias;
    pos += vel * dt + 0.5 * corrected_accel * dt * dt;
    vel += corrected_accel * dt;

    const double a[3][3]{
        {1.0, dt, -0.5 * dt * dt},
        {0.0, 1.0, -dt},
        {0.0, 0.0, 1.0},
    };

    double ap[3][3]{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            for (int k = 0; k < 3; ++k) {
                ap[r][c] += a[r][k] * p[k][c];
            }
        }
    }

    double next_p[3][3]{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            for (int k = 0; k < 3; ++k) {
                next_p[r][c] += ap[r][k] * a[c][k];
            }
        }
    }

    const double q_acc = accel_noise * accel_noise;
    const double q_bias = bias_noise * bias_noise;
    next_p[0][0] += 0.25 * dt * dt * dt * dt * q_acc;
    next_p[1][1] += dt * dt * q_acc;
    next_p[2][2] += dt * q_bias;

    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            p[r][c] = next_p[r][c];
        }
    }
}

void MultiSensorNavigation::AxisKalman::updatePosition(double measured_pos, double variance, double weight) {
    const double h[3]{1.0, 0.0, 0.0};
    updateScalar(measured_pos, h, variance, weight);
}

void MultiSensorNavigation::AxisKalman::updateVelocity(double measured_vel, double variance, double weight) {
    const double h[3]{0.0, 1.0, 0.0};
    updateScalar(measured_vel, h, variance, weight);
}

void MultiSensorNavigation::AxisKalman::updateScalar(double measured, const double h[3], double variance, double weight) {
    if (weight <= 0.0) {
        return;
    }
    const double r = std::max(1e-8, variance / weight);
    const double state[3]{pos, vel, bias};
    const double predicted = h[0] * state[0] + h[1] * state[1] + h[2] * state[2];
    const double innovation = measured - predicted;

    double ph[3]{};
    for (int row = 0; row < 3; ++row) {
        ph[row] = p[row][0] * h[0] + p[row][1] * h[1] + p[row][2] * h[2];
    }

    const double s = h[0] * ph[0] + h[1] * ph[1] + h[2] * ph[2] + r;
    if (s < 1e-12) {
        return;
    }
    const double k[3]{ph[0] / s, ph[1] / s, ph[2] / s};

    pos += k[0] * innovation;
    vel += k[1] * innovation;
    bias += k[2] * innovation;

    double kh[3][3]{};
    for (int row = 0; row < 3; ++row) {
        for (int col = 0; col < 3; ++col) {
            kh[row][col] = k[row] * h[col];
        }
    }

    double next_p[3][3]{};
    for (int row = 0; row < 3; ++row) {
        for (int col = 0; col < 3; ++col) {
            next_p[row][col] = p[row][col];
            for (int kk = 0; kk < 3; ++kk) {
                next_p[row][col] -= kh[row][kk] * p[kk][col];
            }
        }
    }

    for (int row = 0; row < 3; ++row) {
        for (int col = 0; col < 3; ++col) {
            p[row][col] = 0.5 * (next_p[row][col] + next_p[col][row]);
        }
    }
}

} // namespace flight_sim
