#pragma once

#include "flight_sim/math.hpp"

#include <string>
#include <vector>

namespace flight_sim {

struct SimulationConfig {
    double duration_s{60.0};
    double dt_s{0.002};
    double mass_kg{0.83};
    double gravity_mps2{9.78};
    Vec3 inertia_kgm2{0.0018, 0.0018, 0.0025};
    double linear_drag{0.12};
    std::string output_csv{"simulation.csv"};
    std::string output_html{"dashboard.html"};
    bool write_html{true};
    double reference_lat_deg{31.2304};
    double reference_lon_deg{121.4737};
    double reference_alt_m{4.0};
    bool enable_uwb{true};
    bool enable_optical_flow{true};
    bool enable_magnetometer{true};
    std::string trajectory_mode{"default"};
    std::string trajectory_file{};
};

struct AttackConfig {
    double start_s{20.0};
    double end_s{34.0};
    Vec3 gps_offset_m{4.0, -2.0, 0.8};
    double pseudorange_delay_m{8.0};
    double ramp_s{2.0};
};

struct DetectorConfig {
    double gps_residual_threshold_m{0.75};
    double glrt_false_alarm_rate{1e-3};
    double glrt_threshold{0.0};
    double pseudorange_noise_sigma_m{0.35};
    double lms_step_size{0.08};
    int lms_filter_order{5};
    int glrt_warmup_samples{100};
    int min_pseudorange_satellites{4};
    int consecutive_samples{1};
};

struct Ephemeris {
    int prn{0};
    double semi_major_axis_m{26560000.0};
    double eccentricity{0.01};
    double inclination_rad{55.0 * kPi / 180.0};
    double raan_rad{0.0};
    double argument_of_perigee_rad{0.0};
    double mean_anomaly_rad{0.0};
    double delta_mean_motion_radps{0.0};
    double epoch_s{0.0};
    double clock_bias_m{0.0};
    double clock_drift_mps{0.0};
};

struct SatelliteState {
    int prn{0};
    double t_s{0.0};
    Vec3 ecef_position_m{};
    Vec3 ecef_velocity_mps{};
    double clock_bias_m{0.0};
    double clock_drift_mps{0.0};
};

struct PseudorangeMeasurement {
    int prn{0};
    double t_s{0.0};
    SatelliteState satellite{};
    double true_pseudorange_m{0.0};
    double measured_pseudorange_m{0.0};
    double noise_m{0.0};
    double multipath_m{0.0};
    double attack_delay_m{0.0};
    double filtered_pseudorange_m{0.0};
    double predicted_pseudorange_m{0.0};
    double residual_m{0.0};
    double disturbance_estimate_m{0.0};
    double azimuth_rad{0.0};
    double elevation_rad{0.0};
    bool attacked{false};
    bool valid{false};
};

struct DroneState {
    Vec3 position_m{};
    Vec3 velocity_mps{};
    Quaternion attitude{};
    Vec3 omega_radps{};
};

struct SensorSample {
    double t_s{0.0};
    Vec3 gyro_radps{};
    Vec3 accel_body_mps2{};
    Vec3 gps_position_m{};
    Vec3 gps_velocity_mps{};
    Vec3 uwb_position_m{};
    Vec3 optical_flow_velocity_mps{};
    double magnetometer_yaw_rad{0.0};
    double baro_altitude_m{0.0};
    Vec3 receiver_ecef_m{};
    Vec3 receiver_enu_m{};
    std::vector<PseudorangeMeasurement> pseudoranges{};
    bool gps_valid{false};
    bool gps_attacked{false};
    bool uwb_valid{false};
    bool optical_flow_valid{false};
    bool magnetometer_valid{false};
};

struct NavEstimate {
    Vec3 position_m{};
    Vec3 velocity_mps{};
    Quaternion attitude{};
    Vec3 omega_radps{};
    Vec3 accel_bias_mps2{};
};

struct TrajectorySetpoint {
    Vec3 position_m{};
    Vec3 velocity_mps{};
    Vec3 acceleration_mps2{};
    double yaw_rad{0.0};
};

struct ControlCommand {
    double thrust_n{0.0};
    Vec3 moment_nm{};
    Vec3 desired_accel_mps2{};
    Quaternion desired_attitude{};
};

struct DetectionState {
    Vec3 gps_residual_m{};
    double gps_residual_norm_m{0.0};
    std::vector<PseudorangeMeasurement> pseudoranges{};
    double pseudorange_residual_mean_m{0.0};
    double pseudorange_residual_rms_m{0.0};
    double pseudorange_residual_max_abs_m{0.0};
    double glrt_statistic{0.0};
    double glrt_threshold{0.0};
    double glrt_false_alarm_rate{0.0};
    bool glrt_detected{false};
    Vec3 disturbance_estimate{};
    bool gps_spoof_detected{false};
};

} // namespace flight_sim
