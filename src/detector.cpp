#include "flight_sim/detector.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace flight_sim {

GpsSpoofDetector::GpsSpoofDetector(DetectorConfig detector_config, SimulationConfig sim_config)
    : detector_config_(detector_config),
      sim_config_(sim_config),
      lms_filter_(detector_config_.lms_filter_order, detector_config_.lms_step_size) {}

DetectionState GpsSpoofDetector::update(
    const SensorSample& sample,
    const NavEstimate& predicted,
    const Vec3& attitude_error,
    const Vec3& body_rate,
    const Vec3& moment_command) {
    DetectionState state = last_state_;
    if (sample.gps_valid) {
        state.gps_residual_m = sample.gps_position_m - predicted.position_m;
        state.gps_residual_norm_m = state.gps_residual_m.norm();
        updatePseudorangeGlrt(sample, predicted, state);

        if (state.gps_residual_norm_m > detector_config_.gps_residual_threshold_m) {
            ++gps_residual_count_;
        } else {
            gps_residual_count_ = 0;
        }
        const bool gps_residual_detected =
            gps_residual_count_ >= detector_config_.consecutive_samples;
        state.gps_spoof_detected = state.gps_spoof_detected || gps_residual_detected;
    }

    state.disturbance_estimate = updateDisturbanceObserver(
        attitude_error, body_rate, moment_command, sim_config_.dt_s);
    last_state_ = state;
    return state;
}

void GpsSpoofDetector::updatePseudorangeGlrt(
    const SensorSample& sample,
    const NavEstimate& predicted,
    DetectionState& state) {
    state.pseudoranges = sample.pseudoranges;
    state.pseudorange_residual_mean_m = 0.0;
    state.pseudorange_residual_rms_m = 0.0;
    state.pseudorange_residual_max_abs_m = 0.0;
    state.glrt_statistic = 0.0;
    state.glrt_false_alarm_rate = detector_config_.glrt_false_alarm_rate;

    if (state.pseudoranges.size() < static_cast<std::size_t>(detector_config_.min_pseudorange_satellites)) {
        state.glrt_detected = false;
        state.gps_spoof_detected = false;
        glrt_detection_count_ = 0;
        return;
    }

    const GeodeticPosition reference = referenceGeodetic(sim_config_);
    const Vec3 receiver_ecef = enuToEcef(predicted.position_m, reference);
    const Vec3 receiver_velocity_ecef = enuVectorToEcef(predicted.velocity_mps, reference);
    const double sigma = std::max(0.05, detector_config_.pseudorange_noise_sigma_m);
    const double variance = sigma * sigma;

    double residual_sum = 0.0;
    double residual_sq_sum = 0.0;
    int valid_count = 0;

    for (PseudorangeMeasurement& measurement : state.pseudoranges) {
        if (!measurement.valid) {
            continue;
        }

        const double filtered = lms_filter_.update(measurement.prn, measurement.measured_pseudorange_m);
        const double geometric = geometricPseudorange(receiver_ecef, measurement.satellite);
        const Vec3 los = (measurement.satellite.ecef_position_m - receiver_ecef).normalized();
        const double range_rate = dot(measurement.satellite.ecef_velocity_mps - receiver_velocity_ecef, los);
        const PseudorangePrediction prediction = pseudorange_predictor_.update(
            measurement.prn,
            measurement.t_s,
            filtered,
            geometric,
            range_rate,
            variance);

        measurement.filtered_pseudorange_m = filtered;
        measurement.predicted_pseudorange_m = prediction.predicted_pseudorange_m;
        measurement.residual_m = prediction.residual_m;
        measurement.disturbance_estimate_m = prediction.disturbance_estimate_m;

        residual_sum += measurement.residual_m;
        residual_sq_sum += measurement.residual_m * measurement.residual_m;
        state.pseudorange_residual_max_abs_m =
            std::max(state.pseudorange_residual_max_abs_m, std::abs(measurement.residual_m));
        state.glrt_statistic += measurement.residual_m * measurement.residual_m / variance;
        ++valid_count;
    }

    if (valid_count <= 0) {
        state.glrt_detected = false;
        state.gps_spoof_detected = false;
        glrt_detection_count_ = 0;
        return;
    }

    state.pseudorange_residual_mean_m = residual_sum / static_cast<double>(valid_count);
    state.pseudorange_residual_rms_m = std::sqrt(residual_sq_sum / static_cast<double>(valid_count));
    state.glrt_threshold = detector_config_.glrt_threshold > 0.0
        ? detector_config_.glrt_threshold
        : chiSquareThresholdForFalseAlarm(detector_config_.glrt_false_alarm_rate, valid_count);

    ++pseudorange_update_count_;
    const bool past_warmup = pseudorange_update_count_ > detector_config_.glrt_warmup_samples;
    if (!past_warmup) {
        state.glrt_statistic = 0.0;
        state.glrt_detected = false;
        state.gps_spoof_detected = false;
        glrt_detection_count_ = 0;
        return;
    }
    state.glrt_detected = past_warmup && state.glrt_statistic > state.glrt_threshold;
    if (state.glrt_detected) {
        ++glrt_detection_count_;
    } else {
        glrt_detection_count_ = 0;
    }
    state.gps_spoof_detected = glrt_detection_count_ >= detector_config_.consecutive_samples;
}

Vec3 GpsSpoofDetector::updateDisturbanceObserver(
    const Vec3& attitude_error,
    const Vec3& body_rate,
    const Vec3& moment_command,
    double dt_s) {
    const double ix = std::max(1e-9, sim_config_.inertia_kgm2.x);
    const double iy = std::max(1e-9, sim_config_.inertia_kgm2.y);
    const double iz = std::max(1e-9, sim_config_.inertia_kgm2.z);

    const double p = body_rate.x;
    const double q = body_rate.y;
    const double r = body_rate.z;

    const std::array<double, 6> u{
        attitude_error.x,
        attitude_error.y,
        attitude_error.z,
        p,
        q,
        r,
    };

    const std::array<double, 6> fw{
        p,
        q,
        r,
        (iy - iz) / ix * q * r,
        (iz - ix) / iy * p * r,
        (ix - iy) / iz * p * q,
    };

    const Vec3 angular_accel{
        moment_command.x / ix,
        moment_command.y / iy,
        moment_command.z / iz,
    };

    std::array<double, 6> dz{};
    dz[0] = -(observer_state_[0] + u[0] + fw[0]);
    dz[1] = -(observer_state_[1] + u[1] + fw[1] + angular_accel.x);
    dz[2] = -(observer_state_[2] + u[2] + fw[2]);
    dz[3] = -(observer_state_[3] + u[3] + fw[3] + angular_accel.y);
    dz[4] = -(observer_state_[4] + u[4] + fw[4]);
    dz[5] = -(observer_state_[5] + u[5] + fw[5] + angular_accel.z);

    for (std::size_t i = 0; i < observer_state_.size(); ++i) {
        observer_state_[i] += dz[i] * dt_s;
    }

    return {observer_state_[0], observer_state_[2], observer_state_[4]};
}

} // namespace flight_sim
