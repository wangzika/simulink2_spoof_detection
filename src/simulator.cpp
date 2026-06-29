#include "flight_sim/simulator.hpp"

#include <iomanip>
#include <iostream>

namespace flight_sim {

Simulator::Simulator(SimulationConfig sim_config, AttackConfig attack_config, DetectorConfig detector_config)
    : sim_config_(std::move(sim_config)),
      attack_config_(attack_config),
      detector_config_(detector_config),
      inav_params_(InavParameters::defaults()),
      dynamics_(sim_config_),
      sensors_(sim_config_, attack_config_),
      navigation_(sim_config_, inav_params_),
      controller_(sim_config_),
      detector_(detector_config_, sim_config_),
      state_machine_(inav_params_, sim_config_) {}

int Simulator::run() {
    std::string trajectory_error;
    if (!trajectory_.setMode(sim_config_.trajectory_mode, trajectory_error)) {
        std::cerr << trajectory_error << "\n";
        return 2;
    }
    if (!sim_config_.trajectory_file.empty() &&
        !trajectory_.loadWaypointCsv(sim_config_.trajectory_file, trajectory_error)) {
        std::cerr << trajectory_error << "\n";
        return 2;
    }

    std::ofstream out(sim_config_.output_csv);
    if (!out) {
        std::cerr << "Failed to open output CSV: " << sim_config_.output_csv << "\n";
        return 1;
    }
    writeHeader(out);

    DroneState initial;
    initial.position_m = {0.0, 0.0, 0.0};
    initial.velocity_mps = {0.0, 0.0, 0.0};
    initial.attitude = {};
    initial.omega_radps = {};

    dynamics_.reset(initial);
    navigation_.reset(initial);

    ControlCommand command;
    command.thrust_n = sim_config_.mass_kg * sim_config_.gravity_mps2;

    DetectionState detection;
    const int steps = static_cast<int>(sim_config_.duration_s / sim_config_.dt_s);
    const int output_stride = std::max(1, static_cast<int>(0.02 / sim_config_.dt_s));

    int detected_samples = 0;
    int attacked_samples = 0;
    int gps_rejected_samples = 0;
    bool hold_reference_active = false;
    bool landing_reference_active = false;
    Vec3 hold_position{};
    Vec3 landing_start_position{};
    double landing_start_time_s = 0.0;

    for (int step = 0; step <= steps; ++step) {
        const double t = step * sim_config_.dt_s;
        const DroneState truth = dynamics_.state();
        const SensorSample sensor = sensors_.sample(t, truth, command);

        navigation_.propagate(sensor);
        const NavEstimate predicted = navigation_.estimate();

        const Mat3 current_r = predicted.attitude.toRotationMatrix();
        const Mat3 desired_r = command.desired_attitude.toRotationMatrix();
        const Vec3 attitude_error =
            0.5 * (cross(current_r.col(0), desired_r.col(0)) +
                   cross(current_r.col(1), desired_r.col(1)) +
                   cross(current_r.col(2), desired_r.col(2)));

        detection = detector_.update(
            sensor, predicted, attitude_error, predicted.omega_radps, command.moment_nm);

        const ModeDecision mode = state_machine_.update(t, sensor, detection);
        navigation_.correct(sensor, mode.gps_trusted);

        const NavEstimate corrected_nav = navigation_.estimate();
        const TrajectorySetpoint mission_ref = trajectory_.sample(t);
        TrajectorySetpoint ref = mission_ref;

        if (mode.mode == FlightMode::GpsRejected || mode.mode == FlightMode::GpsReacquire) {
            if (!hold_reference_active) {
                hold_position = corrected_nav.position_m;
                hold_reference_active = true;
            }
            ref.position_m = {corrected_nav.position_m.x, corrected_nav.position_m.y, hold_position.z};
            ref.velocity_mps = {corrected_nav.velocity_mps.x, corrected_nav.velocity_mps.y, 0.0};
            ref.acceleration_mps2 = {};
        } else {
            hold_reference_active = false;
        }

        if (mode.mode == FlightMode::Landing) {
            if (!landing_reference_active) {
                landing_start_position = corrected_nav.position_m;
                landing_start_time_s = t;
                landing_reference_active = true;
            }
            const double descent_rate_mps = 0.35;
            const double target_z = std::max(0.0, landing_start_position.z - descent_rate_mps * (t - landing_start_time_s));
            ref.position_m = {corrected_nav.position_m.x, corrected_nav.position_m.y, target_z};
            ref.velocity_mps = {
                corrected_nav.velocity_mps.x,
                corrected_nav.velocity_mps.y,
                target_z > 0.0 ? -descent_rate_mps : 0.0,
            };
            ref.acceleration_mps2 = {};
        } else {
            landing_reference_active = false;
        }

        command = controller_.update(ref, corrected_nav);
        dynamics_.step(command);

        if (sensor.gps_attacked) {
            ++attacked_samples;
        }
        if (detection.gps_spoof_detected) {
            ++detected_samples;
        }
        if (!mode.gps_trusted) {
            ++gps_rejected_samples;
        }

        if (step % output_stride == 0) {
            writeSample(out, t, truth, corrected_nav, sensor, ref, command, detection, mode);
            visualizer_.addSample(t, truth, corrected_nav, sensor, ref, detection, mode);
        }
    }

    if (sim_config_.write_html) {
        visualizer_.writeHtml(sim_config_.output_html, sim_config_);
    }

    std::cout << "Simulation complete\n";
    std::cout << "  output: " << sim_config_.output_csv << "\n";
    if (sim_config_.write_html) {
        std::cout << "  dashboard: " << sim_config_.output_html << "\n";
    }
    std::cout << "  trajectory: " << trajectory_.modeName() << "\n";
    std::cout << "  duration: " << sim_config_.duration_s << " s\n";
    std::cout << "  attacked samples: " << attacked_samples << "\n";
    std::cout << "  GLRT detected samples: " << detected_samples << "\n";
    std::cout << "  gps rejected samples: " << gps_rejected_samples << "\n";
    return 0;
}

void Simulator::writeHeader(std::ofstream& out) {
    out << "time_s,"
        << "true_x,true_y,true_z,true_vx,true_vy,true_vz,"
        << "est_x,est_y,est_z,est_vx,est_vy,est_vz,"
        << "gps_x,gps_y,gps_z,"
        << "uwb_x,uwb_y,uwb_z,flow_vx,flow_vy,mag_yaw,"
        << "uwb_valid,flow_valid,mag_valid,"
        << "ref_x,ref_y,ref_z,"
        << "attack_active,detected,residual_norm,"
        << "pseudorange_residual_mean,pseudorange_residual_rms,pseudorange_residual_max_abs,"
        << "glrt_statistic,glrt_threshold,glrt_false_alarm_rate,glrt_detected,pseudorange_satellites,"
        << "flight_mode,gps_trusted,"
        << "accel_bias_x,accel_bias_y,accel_bias_z,"
        << "disturbance_x,disturbance_y,disturbance_z,"
        << "thrust_n,moment_x,moment_y,moment_z\n";
}

void Simulator::writeSample(
    std::ofstream& out,
    double t_s,
    const DroneState& truth,
    const NavEstimate& nav,
    const SensorSample& sensor,
    const TrajectorySetpoint& ref,
    const ControlCommand& command,
    const DetectionState& detection,
    const ModeDecision& mode) {
    out << std::fixed << std::setprecision(6)
        << t_s << ","
        << truth.position_m.x << "," << truth.position_m.y << "," << truth.position_m.z << ","
        << truth.velocity_mps.x << "," << truth.velocity_mps.y << "," << truth.velocity_mps.z << ","
        << nav.position_m.x << "," << nav.position_m.y << "," << nav.position_m.z << ","
        << nav.velocity_mps.x << "," << nav.velocity_mps.y << "," << nav.velocity_mps.z << ","
        << sensor.gps_position_m.x << "," << sensor.gps_position_m.y << "," << sensor.gps_position_m.z << ","
        << sensor.uwb_position_m.x << "," << sensor.uwb_position_m.y << "," << sensor.uwb_position_m.z << ","
        << sensor.optical_flow_velocity_mps.x << "," << sensor.optical_flow_velocity_mps.y << ","
        << sensor.magnetometer_yaw_rad << ","
        << (sensor.uwb_valid ? 1 : 0) << ","
        << (sensor.optical_flow_valid ? 1 : 0) << ","
        << (sensor.magnetometer_valid ? 1 : 0) << ","
        << ref.position_m.x << "," << ref.position_m.y << "," << ref.position_m.z << ","
        << (sensor.gps_attacked ? 1 : 0) << ","
        << (detection.gps_spoof_detected ? 1 : 0) << ","
        << detection.gps_residual_norm_m << ","
        << detection.pseudorange_residual_mean_m << ","
        << detection.pseudorange_residual_rms_m << ","
        << detection.pseudorange_residual_max_abs_m << ","
        << detection.glrt_statistic << ","
        << detection.glrt_threshold << ","
        << detection.glrt_false_alarm_rate << ","
        << (detection.glrt_detected ? 1 : 0) << ","
        << detection.pseudoranges.size() << ","
        << "\"" << mode.mode_name << "\","
        << (mode.gps_trusted ? 1 : 0) << ","
        << nav.accel_bias_mps2.x << "," << nav.accel_bias_mps2.y << "," << nav.accel_bias_mps2.z << ","
        << detection.disturbance_estimate.x << "," << detection.disturbance_estimate.y << "," << detection.disturbance_estimate.z << ","
        << command.thrust_n << ","
        << command.moment_nm.x << "," << command.moment_nm.y << "," << command.moment_nm.z
        << "\n";
}

} // namespace flight_sim
