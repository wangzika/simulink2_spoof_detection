#include "flight_sim/flight_state_machine.hpp"
#include "flight_sim/gnss.hpp"
#include "flight_sim/navigation.hpp"
#include "flight_sim/simulator.hpp"
#include "flight_sim/trajectory.hpp"

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

int g_failures = 0;

void expect(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << "\n";
        ++g_failures;
    }
}

void expectNear(double actual, double expected, double tolerance, const std::string& message) {
    if (std::abs(actual - expected) > tolerance) {
        std::cerr << "FAIL: " << message << " actual=" << actual << " expected=" << expected
                  << " tolerance=" << tolerance << "\n";
        ++g_failures;
    }
}

std::vector<std::string> splitCsvLine(const std::string& line) {
    std::vector<std::string> fields;
    std::string field;
    bool in_quotes = false;
    for (char c : line) {
        if (c == '"') {
            in_quotes = !in_quotes;
            continue;
        }
        if (c == ',' && !in_quotes) {
            fields.push_back(field);
            field.clear();
        } else {
            field.push_back(c);
        }
    }
    fields.push_back(field);
    return fields;
}

struct CsvSummary {
    int rows{0};
    int attack_rows{0};
    int detected_rows{0};
    int glrt_rows{0};
    int rejected_rows{0};
    int uwb_rows{0};
    int optical_flow_rows{0};
    int magnetometer_rows{0};
    double min_true_z{1e9};
    double max_true_z{-1e9};
    double max_est_error_m{0.0};
    double max_gps_residual_m{0.0};
    double max_pseudorange_rms_m{0.0};
    double max_glrt{0.0};
    double last_true_z{0.0};
    double last_time_s{0.0};
};

CsvSummary summarizeCsv(const std::string& path) {
    std::ifstream in(path);
    expect(static_cast<bool>(in), "CSV exists: " + path);
    CsvSummary summary;
    std::string line;
    std::getline(in, line);
    const auto header = splitCsvLine(line);
    std::unordered_map<std::string, std::size_t> columns;
    for (std::size_t i = 0; i < header.size(); ++i) {
        columns[header[i]] = i;
    }
    auto column = [&](const std::string& name) -> std::size_t {
        const auto it = columns.find(name);
        expect(it != columns.end(), "CSV contains column: " + name);
        return it == columns.end() ? 0 : it->second;
    };
    auto asDouble = [&](const std::vector<std::string>& row, const std::string& name) -> double {
        return std::strtod(row.at(column(name)).c_str(), nullptr);
    };

    while (std::getline(in, line)) {
        if (line.empty()) {
            continue;
        }
        const auto row = splitCsvLine(line);
        expect(row.size() == header.size(), "CSV row has expected column count");
        if (row.size() != header.size()) {
            continue;
        }

        const double true_x = asDouble(row, "true_x");
        const double true_y = asDouble(row, "true_y");
        const double true_z = asDouble(row, "true_z");
        const double est_x = asDouble(row, "est_x");
        const double est_y = asDouble(row, "est_y");
        const double est_z = asDouble(row, "est_z");
        const double gps_residual = asDouble(row, "residual_norm");
        const double pseudorange_rms = asDouble(row, "pseudorange_residual_rms");
        const double glrt = asDouble(row, "glrt_statistic");

        ++summary.rows;
        summary.attack_rows += asDouble(row, "attack_active") > 0.5 ? 1 : 0;
        summary.detected_rows += asDouble(row, "detected") > 0.5 ? 1 : 0;
        summary.glrt_rows += asDouble(row, "glrt_detected") > 0.5 ? 1 : 0;
        summary.rejected_rows += asDouble(row, "gps_trusted") < 0.5 ? 1 : 0;
        summary.uwb_rows += asDouble(row, "uwb_valid") > 0.5 ? 1 : 0;
        summary.optical_flow_rows += asDouble(row, "flow_valid") > 0.5 ? 1 : 0;
        summary.magnetometer_rows += asDouble(row, "mag_valid") > 0.5 ? 1 : 0;
        summary.min_true_z = std::min(summary.min_true_z, true_z);
        summary.max_true_z = std::max(summary.max_true_z, true_z);
        const double est_error = std::sqrt(
            (true_x - est_x) * (true_x - est_x) +
            (true_y - est_y) * (true_y - est_y) +
            (true_z - est_z) * (true_z - est_z));
        summary.max_est_error_m = std::max(summary.max_est_error_m, est_error);
        summary.max_gps_residual_m = std::max(summary.max_gps_residual_m, gps_residual);
        summary.max_pseudorange_rms_m = std::max(summary.max_pseudorange_rms_m, pseudorange_rms);
        summary.max_glrt = std::max(summary.max_glrt, glrt);
        summary.last_true_z = true_z;
        summary.last_time_s = asDouble(row, "time_s");
    }
    return summary;
}

void testCoordinateTransforms() {
    flight_sim::SimulationConfig config;
    const flight_sim::GeodeticPosition reference = flight_sim::referenceGeodetic(config);
    const flight_sim::Vec3 enu{12.4, -7.2, 3.6};
    const flight_sim::Vec3 round_trip = flight_sim::ecefToEnu(flight_sim::enuToEcef(enu, reference), reference);
    expectNear(round_trip.x, enu.x, 1e-6, "ENU/ECEF round trip x");
    expectNear(round_trip.y, enu.y, 1e-6, "ENU/ECEF round trip y");
    expectNear(round_trip.z, enu.z, 1e-6, "ENU/ECEF round trip z");

    const flight_sim::Vec3 vector_round_trip =
        flight_sim::ecefVectorToEnu(flight_sim::enuVectorToEcef(enu, reference), reference);
    expectNear(vector_round_trip.x, enu.x, 1e-9, "ENU/ECEF vector round trip x");
    expectNear(vector_round_trip.y, enu.y, 1e-9, "ENU/ECEF vector round trip y");
    expectNear(vector_round_trip.z, enu.z, 1e-9, "ENU/ECEF vector round trip z");
}

void testChiSquareThreshold() {
    const double threshold = flight_sim::chiSquareThresholdForFalseAlarm(1e-3, 8);
    expectNear(threshold, 26.1245, 0.02, "chi-square threshold dof=8 alpha=0.001");
    expect(flight_sim::chiSquareThresholdForFalseAlarm(0.05, 8) < threshold,
           "looser false alarm rate lowers threshold");
}

void testTrajectoryContinuity() {
    flight_sim::TrajectoryPlanner planner;
    const auto before_transition = planner.sample(3.999);
    const auto after_transition = planner.sample(4.001);
    expect((after_transition.position_m - before_transition.position_m).norm() < 0.01,
           "takeoff-to-transition reference is continuous");

    const auto before_circle = planner.sample(7.999);
    const auto after_circle = planner.sample(8.001);
    expect((after_circle.position_m - before_circle.position_m).norm() < 0.01,
           "transition-to-circle reference is continuous");
}

void testWaypointTrajectoryCsv() {
    const std::string path = "test_waypoints.csv";
    {
        std::ofstream out(path);
        out << "time_s,x,y,z,yaw_rad\n"
            << "0,0,0,0,0\n"
            << "4,0,0,1.5,0\n"
            << "8,2,0,1.5,1.5707963268\n";
    }

    flight_sim::TrajectoryPlanner planner;
    std::string error;
    expect(planner.loadWaypointCsv(path, error), "waypoint trajectory CSV loads");
    expect(planner.hasCustomWaypoints(), "waypoint trajectory is active");
    expect(planner.modeName() == "waypoints", "waypoint trajectory reports mode");

    const auto start = planner.sample(0.0);
    const auto mid = planner.sample(5.0);
    const auto end = planner.sample(10.0);

    expectNear(start.position_m.z, 0.0, 1e-9, "waypoint start z");
    expect(mid.position_m.x > 0.0 && mid.position_m.x < 2.0, "waypoint mid x interpolates");
    expect(mid.velocity_mps.x > 0.0, "waypoint mid velocity has feed-forward");
    expect(std::abs(mid.acceleration_mps2.x) > 1e-6, "waypoint mid acceleration has feed-forward");
    expectNear(end.position_m.x, 2.0, 1e-9, "waypoint end holds x");
    expectNear(end.position_m.z, 1.5, 1e-9, "waypoint end holds z");
}

void testStateMachineLandingTimeUsesConfig() {
    flight_sim::SimulationConfig config;
    config.duration_s = 10.0;
    flight_sim::FlightStateMachine state_machine(flight_sim::InavParameters::defaults(), config);
    flight_sim::SensorSample sensor;
    flight_sim::DetectionState detection;

    state_machine.update(0.0, sensor, detection);
    state_machine.update(1.0, sensor, detection);
    state_machine.update(4.0, sensor, detection);
    const auto decision = state_machine.update(9.1, sensor, detection);
    expect(decision.mode == flight_sim::FlightMode::Landing, "landing mode follows configured duration");
}

void testAuxiliarySensorsFuseWithoutGps() {
    flight_sim::SimulationConfig config;
    flight_sim::MultiSensorNavigation navigation(config, flight_sim::InavParameters::defaults());

    flight_sim::DroneState initial;
    initial.position_m = {5.0, 5.0, 0.0};
    initial.velocity_mps = {};
    navigation.reset(initial);

    flight_sim::SensorSample sample;
    sample.t_s = 0.01;
    sample.gyro_radps = {};
    sample.accel_body_mps2 = {0.0, 0.0, config.gravity_mps2};
    sample.baro_altitude_m = 1.0;
    sample.gps_valid = true;
    sample.uwb_valid = true;
    sample.optical_flow_valid = true;
    sample.magnetometer_valid = true;
    sample.gps_position_m = {50.0, 50.0, 10.0};
    sample.gps_velocity_mps = {8.0, 8.0, 0.0};
    sample.uwb_position_m = {1.0, -2.0, 1.0};
    sample.optical_flow_velocity_mps = {0.35, -0.2, 0.0};
    sample.magnetometer_yaw_rad = 0.2;

    navigation.propagate(sample);
    const auto before = navigation.estimate();
    navigation.correct(sample, false);
    const auto after = navigation.estimate();

    const double before_uwb_distance = (before.position_m - sample.uwb_position_m).norm();
    const double after_uwb_distance = (after.position_m - sample.uwb_position_m).norm();
    expect(after_uwb_distance < before_uwb_distance, "UWB aiding corrects position when GPS is untrusted");
    expect(after.velocity_mps.x > before.velocity_mps.x, "optical flow corrects x velocity");
    expect(after.velocity_mps.y < before.velocity_mps.y, "optical flow corrects y velocity");
    expect(std::abs(after.attitude.yawRad()) > std::abs(before.attitude.yawRad()),
           "magnetometer corrects yaw when GPS is untrusted");
}

void testNoAttackSimulation() {
    flight_sim::SimulationConfig sim;
    sim.duration_s = 12.0;
    sim.dt_s = 0.004;
    sim.output_csv = "test_no_attack.csv";
    sim.write_html = false;

    flight_sim::AttackConfig attack;
    attack.start_s = 99.0;
    attack.end_s = 100.0;

    flight_sim::DetectorConfig detector;

    flight_sim::Simulator simulator(sim, attack, detector);
    expect(simulator.run() == 0, "no-attack simulation exits successfully");
    const CsvSummary summary = summarizeCsv(sim.output_csv);

    expect(summary.rows > 500, "no-attack simulation writes expected rows");
    expect(summary.uwb_rows > 20, "no-attack simulation writes UWB updates");
    expect(summary.optical_flow_rows > 100, "no-attack simulation writes optical-flow updates");
    expect(summary.magnetometer_rows > 50, "no-attack simulation writes magnetometer updates");
    expect(summary.attack_rows == 0, "no-attack simulation has no attack rows");
    expect(summary.detected_rows == 0, "no-attack simulation has no spoof detections");
    expect(summary.rejected_rows == 0, "no-attack simulation keeps GPS trusted");
    expect(summary.min_true_z > -0.2, "no-attack flight does not fall below ground significantly");
    expect(summary.max_true_z < 3.0, "no-attack flight altitude remains bounded");
    expect(summary.max_est_error_m < 0.8, "no-attack navigation estimate remains close to truth");
}

void testAttackSimulation() {
    flight_sim::SimulationConfig sim;
    sim.duration_s = 16.0;
    sim.dt_s = 0.004;
    sim.output_csv = "test_attack.csv";
    sim.write_html = false;

    flight_sim::AttackConfig attack;
    attack.start_s = 9.0;
    attack.end_s = 13.0;
    attack.gps_offset_m = {4.0, -2.0, 0.8};
    attack.pseudorange_delay_m = 8.0;

    flight_sim::DetectorConfig detector;
    detector.consecutive_samples = 2;

    flight_sim::Simulator simulator(sim, attack, detector);
    expect(simulator.run() == 0, "attack simulation exits successfully");
    const CsvSummary summary = summarizeCsv(sim.output_csv);

    expect(summary.rows > 750, "attack simulation writes expected rows");
    expect(summary.attack_rows > 100, "attack simulation contains attack interval");
    expect(summary.glrt_rows > 20, "GLRT detects sustained spoofing");
    expect(summary.detected_rows > 20, "combined detector detects sustained spoofing");
    expect(summary.rejected_rows > 20, "state machine rejects GPS during attack");
    expect(summary.max_pseudorange_rms_m > 1.0, "attack raises pseudorange residual RMS");
    expect(summary.max_glrt > 26.0, "attack GLRT statistic crosses nominal threshold");
    expect(summary.min_true_z > -0.5, "attack flight remains bounded vertically");
}

} // namespace

int main() {
    testCoordinateTransforms();
    testChiSquareThreshold();
    testTrajectoryContinuity();
    testWaypointTrajectoryCsv();
    testStateMachineLandingTimeUsesConfig();
    testAuxiliarySensorsFuseWithoutGps();
    testNoAttackSimulation();
    testAttackSimulation();

    if (g_failures != 0) {
        std::cerr << g_failures << " test assertion(s) failed\n";
        return 1;
    }
    std::cout << "All flight_sim tests passed\n";
    return 0;
}
