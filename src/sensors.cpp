#include "flight_sim/sensors.hpp"

#include <algorithm>
#include <cmath>

namespace flight_sim {

SensorModel::SensorModel(SimulationConfig config, AttackConfig attack)
    : config_(config),
      attack_(attack),
      ephemerides_(defaultGpsEphemerides()),
      reference_(referenceGeodetic(config_)) {}

SensorSample SensorModel::sample(double t_s, const DroneState& truth, const ControlCommand& last_command) {
    SensorSample sample;
    sample.t_s = t_s;
    sample.gyro_radps = truth.omega_radps + noise3(0.003);
    const Mat3 body_to_world = truth.attitude.toRotationMatrix();
    const Vec3 drag_world = truth.velocity_mps * (-config_.linear_drag);
    const Vec3 specific_force_body =
        Vec3{0.0, 0.0, last_command.thrust_n / config_.mass_kg} +
        body_to_world.transpose() * (drag_world / config_.mass_kg);
    sample.accel_body_mps2 = specific_force_body + noise3(0.035);
    sample.baro_altitude_m = truth.position_m.z + noise(0.04);
    sample.gps_attacked = (t_s >= attack_.start_s && t_s <= attack_.end_s);
    sample.receiver_enu_m = truth.position_m;
    sample.receiver_ecef_m = enuToEcef(truth.position_m, reference_);

    if (t_s + 1e-9 >= next_gps_time_s_) {
        sample.gps_valid = true;
        const Vec3 offset = attackOffset(t_s);
        last_gps_position_ = truth.position_m + offset + noise3(0.08);
        last_gps_velocity_ = truth.velocity_mps + noise3(0.03);
        last_receiver_ecef_ = sample.receiver_ecef_m;
        last_pseudoranges_ = simulatePseudoranges(t_s, truth, sample.gps_attacked);
        next_gps_time_s_ += gps_period_s_;
    } else {
        sample.gps_valid = false;
    }
    sample.gps_position_m = last_gps_position_;
    sample.gps_velocity_mps = last_gps_velocity_;

    if (config_.enable_uwb && t_s + 1e-9 >= next_uwb_time_s_) {
        sample.uwb_valid = true;
        last_uwb_position_ = truth.position_m + Vec3{noise(0.08), noise(0.08), noise(0.16)};
        next_uwb_time_s_ += uwb_period_s_;
    }
    sample.uwb_position_m = last_uwb_position_;

    const bool optical_flow_in_range = truth.position_m.z > 0.15 && truth.position_m.z < 8.0;
    if (config_.enable_optical_flow && optical_flow_in_range &&
        t_s + 1e-9 >= next_optical_flow_time_s_) {
        sample.optical_flow_valid = true;
        last_optical_flow_velocity_ = {
            truth.velocity_mps.x + noise(0.05),
            truth.velocity_mps.y + noise(0.05),
            0.0,
        };
        next_optical_flow_time_s_ += optical_flow_period_s_;
    }
    sample.optical_flow_velocity_mps = last_optical_flow_velocity_;

    if (config_.enable_magnetometer && t_s + 1e-9 >= next_magnetometer_time_s_) {
        sample.magnetometer_valid = true;
        last_magnetometer_yaw_rad_ = truth.attitude.yawRad() + noise(0.012);
        next_magnetometer_time_s_ += magnetometer_period_s_;
    }
    sample.magnetometer_yaw_rad = last_magnetometer_yaw_rad_;

    sample.receiver_ecef_m = last_receiver_ecef_.normSquared() > 0.0 ? last_receiver_ecef_ : sample.receiver_ecef_m;
    sample.pseudoranges = last_pseudoranges_;
    return sample;
}

double SensorModel::noise(double sigma) {
    return sigma * unit_noise_(rng_);
}

Vec3 SensorModel::noise3(double sigma) {
    return {noise(sigma), noise(sigma), noise(sigma)};
}

double SensorModel::attackScale(double t_s) const {
    if (t_s < attack_.start_s || t_s > attack_.end_s) {
        return 0.0;
    }
    const double ramp_in = clamp((t_s - attack_.start_s) / std::max(attack_.ramp_s, 1e-6), 0.0, 1.0);
    const double ramp_out = clamp((attack_.end_s - t_s) / std::max(attack_.ramp_s, 1e-6), 0.0, 1.0);
    return std::min(ramp_in, ramp_out);
}

Vec3 SensorModel::attackOffset(double t_s) const {
    return attack_.gps_offset_m * attackScale(t_s);
}

std::vector<PseudorangeMeasurement> SensorModel::simulatePseudoranges(
    double t_s,
    const DroneState& truth,
    bool attacked) {
    std::vector<PseudorangeMeasurement> measurements;
    measurements.reserve(ephemerides_.size());

    const Vec3 receiver_ecef = enuToEcef(truth.position_m, reference_);
    const Vec3 spoofed_receiver_ecef = enuToEcef(truth.position_m + attackOffset(t_s), reference_);
    const double attack_scale = attackScale(t_s);

    for (const Ephemeris& eph : ephemerides_) {
        const SatelliteState sat = satelliteStateFromEphemeris(eph, t_s);
        const AzElRange aer = azElRange(receiver_ecef, sat.ecef_position_m, reference_);
        const double true_range = geometricPseudorange(receiver_ecef, sat);
        const double spoofed_range = geometricPseudorange(spoofed_receiver_ecef, sat);

        const double low_elevation_gain = clamp((degToRad(35.0) - aer.elevation_rad) / degToRad(45.0), 0.0, 1.0);
        const double multipath_amp = 0.04 + 0.20 * low_elevation_gain;
        const double phase = 0.37 * t_s + 1.73 * static_cast<double>(eph.prn) + 0.025 * truth.position_m.x;
        const double multipath =
            multipath_amp * (0.75 * std::sin(phase) + 0.25 * std::sin(0.41 * phase + 0.8));
        const double white_noise = noise(0.22);
        const double attack_delay =
            attacked ? (spoofed_range - true_range + attack_.pseudorange_delay_m * attack_scale) : 0.0;

        PseudorangeMeasurement measurement;
        measurement.prn = eph.prn;
        measurement.t_s = t_s;
        measurement.satellite = sat;
        measurement.true_pseudorange_m = true_range;
        measurement.noise_m = white_noise;
        measurement.multipath_m = multipath;
        measurement.attack_delay_m = attack_delay;
        measurement.measured_pseudorange_m = true_range + white_noise + multipath + attack_delay;
        measurement.filtered_pseudorange_m = measurement.measured_pseudorange_m;
        measurement.predicted_pseudorange_m = true_range;
        measurement.residual_m = measurement.measured_pseudorange_m - true_range;
        measurement.azimuth_rad = aer.azimuth_rad;
        measurement.elevation_rad = aer.elevation_rad;
        measurement.attacked = attacked;
        measurement.valid = true;
        measurements.push_back(measurement);
    }

    return measurements;
}

} // namespace flight_sim
