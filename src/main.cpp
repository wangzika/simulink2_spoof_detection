#include "flight_sim/simulator.hpp"

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using namespace flight_sim;

namespace {

double parseDouble(const char* value, const char* option) {
    char* end = nullptr;
    const double parsed = std::strtod(value, &end);
    if (end == value || *end != '\0') {
        std::cerr << "Invalid numeric value for " << option << ": " << value << "\n";
        std::exit(2);
    }
    return parsed;
}

std::string trim(const std::string& value) {
    std::size_t begin = 0;
    while (begin < value.size() && std::isspace(static_cast<unsigned char>(value[begin]))) {
        ++begin;
    }
    std::size_t end = value.size();
    while (end > begin && std::isspace(static_cast<unsigned char>(value[end - 1]))) {
        --end;
    }
    return value.substr(begin, end - begin);
}

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

bool parseDoubleConfig(const std::string& value, double& out) {
    char* end = nullptr;
    out = std::strtod(value.c_str(), &end);
    return end != value.c_str() && *end == '\0';
}

bool parseIntConfig(const std::string& value, int& out) {
    double parsed = 0.0;
    if (!parseDoubleConfig(value, parsed)) {
        return false;
    }
    out = static_cast<int>(parsed);
    return true;
}

bool parseBoolConfig(const std::string& value, bool& out) {
    const std::string v = lower(trim(value));
    if (v == "1" || v == "true" || v == "yes" || v == "on") {
        out = true;
        return true;
    }
    if (v == "0" || v == "false" || v == "no" || v == "off") {
        out = false;
        return true;
    }
    return false;
}

std::vector<std::string> splitComma(const std::string& value) {
    std::vector<std::string> parts;
    std::stringstream ss(value);
    std::string part;
    while (std::getline(ss, part, ',')) {
        parts.push_back(trim(part));
    }
    return parts;
}

bool parseVec3Config(const std::string& value, Vec3& out) {
    const auto parts = splitComma(value);
    if (parts.size() != 3) {
        return false;
    }
    return parseDoubleConfig(parts[0], out.x) &&
           parseDoubleConfig(parts[1], out.y) &&
           parseDoubleConfig(parts[2], out.z);
}

bool loadScenarioFile(
    const std::string& path,
    SimulationConfig& sim,
    AttackConfig& attack,
    DetectorConfig& detector,
    std::string& error) {
    std::ifstream in(path);
    if (!in) {
        error = "Failed to open scenario file: " + path;
        return false;
    }
    const std::filesystem::path scenario_path(path);
    const std::filesystem::path scenario_dir = scenario_path.parent_path();

    std::string line;
    int line_number = 0;
    while (std::getline(in, line)) {
        ++line_number;
        std::string cleaned = trim(line);
        if (cleaned.empty() || cleaned[0] == '#') {
            continue;
        }

        const std::size_t comment = cleaned.find('#');
        if (comment != std::string::npos) {
            cleaned = trim(cleaned.substr(0, comment));
        }

        const std::size_t eq = cleaned.find('=');
        if (eq == std::string::npos) {
            error = "Scenario line " + std::to_string(line_number) + " must use key=value syntax";
            return false;
        }

        const std::string key = lower(trim(cleaned.substr(0, eq)));
        const std::string value = trim(cleaned.substr(eq + 1));

        auto setDouble = [&](double& target) -> bool {
            if (!parseDoubleConfig(value, target)) {
                error = "Scenario line " + std::to_string(line_number) + " has invalid numeric value for " + key;
                return false;
            }
            return true;
        };
        auto setInt = [&](int& target) -> bool {
            if (!parseIntConfig(value, target)) {
                error = "Scenario line " + std::to_string(line_number) + " has invalid integer value for " + key;
                return false;
            }
            return true;
        };
        auto setBool = [&](bool& target) -> bool {
            if (!parseBoolConfig(value, target)) {
                error = "Scenario line " + std::to_string(line_number) + " has invalid boolean value for " + key;
                return false;
            }
            return true;
        };

        if (key == "duration" || key == "duration_s") {
            if (!setDouble(sim.duration_s)) return false;
        } else if (key == "dt" || key == "dt_s") {
            if (!setDouble(sim.dt_s)) return false;
        } else if (key == "output" || key == "output_csv") {
            sim.output_csv = value;
        } else if (key == "html" || key == "output_html") {
            sim.output_html = value;
            sim.write_html = true;
        } else if (key == "write_html") {
            if (!setBool(sim.write_html)) return false;
        } else if (key == "trajectory" || key == "trajectory_mode") {
            sim.trajectory_mode = value;
        } else if (key == "trajectory_file" || key == "waypoints" || key == "waypoint_csv") {
            std::filesystem::path trajectory_path(value);
            if (trajectory_path.is_relative() && !scenario_dir.empty()) {
                trajectory_path = scenario_dir / trajectory_path;
            }
            sim.trajectory_file = trajectory_path.string();
        } else if (key == "reference_lat" || key == "reference_lat_deg") {
            if (!setDouble(sim.reference_lat_deg)) return false;
        } else if (key == "reference_lon" || key == "reference_lon_deg") {
            if (!setDouble(sim.reference_lon_deg)) return false;
        } else if (key == "reference_alt" || key == "reference_alt_m") {
            if (!setDouble(sim.reference_alt_m)) return false;
        } else if (key == "enable_uwb") {
            if (!setBool(sim.enable_uwb)) return false;
        } else if (key == "no_uwb") {
            bool disabled = false;
            if (!setBool(disabled)) return false;
            sim.enable_uwb = !disabled;
        } else if (key == "enable_flow" || key == "enable_optical_flow") {
            if (!setBool(sim.enable_optical_flow)) return false;
        } else if (key == "no_flow" || key == "no_optical_flow") {
            bool disabled = false;
            if (!setBool(disabled)) return false;
            sim.enable_optical_flow = !disabled;
        } else if (key == "enable_mag" || key == "enable_magnetometer") {
            if (!setBool(sim.enable_magnetometer)) return false;
        } else if (key == "no_mag" || key == "no_magnetometer") {
            bool disabled = false;
            if (!setBool(disabled)) return false;
            sim.enable_magnetometer = !disabled;
        } else if (key == "attack_start" || key == "attack_start_s") {
            if (!setDouble(attack.start_s)) return false;
        } else if (key == "attack_end" || key == "attack_end_s") {
            if (!setDouble(attack.end_s)) return false;
        } else if (key == "attack_offset" || key == "attack_offset_m") {
            if (!parseVec3Config(value, attack.gps_offset_m)) {
                error = "Scenario line " + std::to_string(line_number) + " needs attack_offset=x,y,z";
                return false;
            }
        } else if (key == "attack_x") {
            if (!setDouble(attack.gps_offset_m.x)) return false;
        } else if (key == "attack_y") {
            if (!setDouble(attack.gps_offset_m.y)) return false;
        } else if (key == "attack_z") {
            if (!setDouble(attack.gps_offset_m.z)) return false;
        } else if (key == "attack_delay" || key == "pseudorange_delay_m") {
            if (!setDouble(attack.pseudorange_delay_m)) return false;
        } else if (key == "attack_ramp" || key == "attack_ramp_s") {
            if (!setDouble(attack.ramp_s)) return false;
        } else if (key == "threshold" || key == "glrt_threshold") {
            if (!setDouble(detector.glrt_threshold)) return false;
        } else if (key == "false_alarm" || key == "glrt_false_alarm_rate") {
            if (!setDouble(detector.glrt_false_alarm_rate)) return false;
        } else if (key == "pseudorange_noise" || key == "pseudorange_noise_sigma_m") {
            if (!setDouble(detector.pseudorange_noise_sigma_m)) return false;
        } else if (key == "gps_threshold" || key == "gps_residual_threshold_m") {
            if (!setDouble(detector.gps_residual_threshold_m)) return false;
        } else if (key == "consecutive" || key == "consecutive_samples") {
            if (!setInt(detector.consecutive_samples)) return false;
        } else if (key == "warmup" || key == "glrt_warmup_samples") {
            if (!setInt(detector.glrt_warmup_samples)) return false;
        } else {
            error = "Scenario line " + std::to_string(line_number) + " has unknown key: " + key;
            return false;
        }
    }

    return true;
}

void printScenarioTemplate() {
    std::cout
        << "# f7_sim scenario file\n"
        << "duration_s=45\n"
        << "dt_s=0.002\n"
        << "output_csv=build/custom_simulation.csv\n"
        << "output_html=build/custom_dashboard.html\n"
        << "write_html=true\n"
        << "trajectory_file=scenarios/custom_square.csv\n"
        << "# trajectory=default|hover|figure8 is used when trajectory_file is empty\n"
        << "attack_start_s=16\n"
        << "attack_end_s=28\n"
        << "attack_offset_m=3.0,-1.5,0.6\n"
        << "pseudorange_delay_m=6.0\n"
        << "attack_ramp_s=1.5\n"
        << "glrt_false_alarm_rate=0.001\n"
        << "enable_uwb=true\n"
        << "enable_optical_flow=true\n"
        << "enable_magnetometer=true\n";
}

void printHelp() {
    std::cout
        << "f7_sim - standalone C++ quadrotor GPS attack simulation\n\n"
        << "Options:\n"
        << "  --scenario PATH          Load key=value scenario config before later CLI overrides\n"
        << "  --print-scenario-template Print a starter scenario config and exit\n"
        << "  --duration SECONDS       Simulation duration, default 60\n"
        << "  --dt SECONDS             Simulation time step, default 0.002\n"
        << "  --output PATH            CSV output path, default simulation.csv\n"
        << "  --html PATH              HTML dashboard output path, default dashboard.html\n"
        << "  --no-html                Disable HTML dashboard generation\n"
        << "  --trajectory MODE        Built-in route: default, hover, or figure8\n"
        << "  --trajectory-file PATH   Waypoint CSV: time_s,x,y,z[,yaw_rad]\n"
        << "  --attack-start SECONDS   GPS spoof attack start time, default 20\n"
        << "  --attack-end SECONDS     GPS spoof attack end time, default 34\n"
        << "  --attack-x METERS        GPS attack X offset, default 4\n"
        << "  --attack-y METERS        GPS attack Y offset, default -2\n"
        << "  --attack-z METERS        GPS attack Z offset, default 0.8\n"
        << "  --attack-delay METERS    Common pseudorange attack delay, default 8\n"
        << "  --attack-ramp SECONDS    Attack ramp-in/out duration, default 2\n"
        << "  --threshold VALUE        Fixed GLRT threshold, default 0 means false-alarm derived\n"
        << "  --false-alarm RATE       GLRT false alarm rate, default 0.001\n"
        << "  --pseudorange-noise M    Pseudorange noise sigma for GLRT, default 0.35\n"
        << "  --gps-threshold METERS   Fallback GPS residual threshold, default 0.75\n"
        << "  --consecutive SAMPLES    Consecutive detections required, default 1\n"
        << "  --warmup SAMPLES         GLRT warmup GPS samples, default 100\n"
        << "  --reference-lat DEG      Local ENU reference latitude, default 31.2304\n"
        << "  --reference-lon DEG      Local ENU reference longitude, default 121.4737\n"
        << "  --reference-alt METERS   Local ENU reference altitude, default 4\n"
        << "  --no-uwb                 Disable UWB position aiding\n"
        << "  --no-flow                Disable optical-flow velocity aiding\n"
        << "  --no-mag                 Disable magnetometer yaw aiding\n"
        << "  --help                   Show this help\n";
}

} // namespace

int main(int argc, char** argv) {
    SimulationConfig sim;
    AttackConfig attack;
    DetectorConfig detector;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto requireValue = [&](const char* option) -> const char* {
            if (i + 1 >= argc) {
                std::cerr << "Missing value for " << option << "\n";
                std::exit(2);
            }
            return argv[++i];
        };

        if (arg == "--duration") {
            sim.duration_s = parseDouble(requireValue("--duration"), "--duration");
        } else if (arg == "--scenario") {
            std::string error;
            if (!loadScenarioFile(requireValue("--scenario"), sim, attack, detector, error)) {
                std::cerr << error << "\n";
                return 2;
            }
        } else if (arg == "--print-scenario-template") {
            printScenarioTemplate();
            return 0;
        } else if (arg == "--dt") {
            sim.dt_s = parseDouble(requireValue("--dt"), "--dt");
        } else if (arg == "--output") {
            sim.output_csv = requireValue("--output");
        } else if (arg == "--html") {
            sim.output_html = requireValue("--html");
            sim.write_html = true;
        } else if (arg == "--no-html") {
            sim.write_html = false;
        } else if (arg == "--trajectory") {
            sim.trajectory_mode = requireValue("--trajectory");
            sim.trajectory_file.clear();
        } else if (arg == "--trajectory-file") {
            sim.trajectory_file = requireValue("--trajectory-file");
        } else if (arg == "--attack-start") {
            attack.start_s = parseDouble(requireValue("--attack-start"), "--attack-start");
        } else if (arg == "--attack-end") {
            attack.end_s = parseDouble(requireValue("--attack-end"), "--attack-end");
        } else if (arg == "--attack-x") {
            attack.gps_offset_m.x = parseDouble(requireValue("--attack-x"), "--attack-x");
        } else if (arg == "--attack-y") {
            attack.gps_offset_m.y = parseDouble(requireValue("--attack-y"), "--attack-y");
        } else if (arg == "--attack-z") {
            attack.gps_offset_m.z = parseDouble(requireValue("--attack-z"), "--attack-z");
        } else if (arg == "--attack-delay") {
            attack.pseudorange_delay_m = parseDouble(requireValue("--attack-delay"), "--attack-delay");
        } else if (arg == "--attack-ramp") {
            attack.ramp_s = parseDouble(requireValue("--attack-ramp"), "--attack-ramp");
        } else if (arg == "--threshold") {
            detector.glrt_threshold = parseDouble(requireValue("--threshold"), "--threshold");
        } else if (arg == "--false-alarm") {
            detector.glrt_false_alarm_rate = parseDouble(requireValue("--false-alarm"), "--false-alarm");
        } else if (arg == "--pseudorange-noise") {
            detector.pseudorange_noise_sigma_m = parseDouble(requireValue("--pseudorange-noise"), "--pseudorange-noise");
        } else if (arg == "--gps-threshold") {
            detector.gps_residual_threshold_m = parseDouble(requireValue("--gps-threshold"), "--gps-threshold");
        } else if (arg == "--consecutive") {
            detector.consecutive_samples = static_cast<int>(parseDouble(requireValue("--consecutive"), "--consecutive"));
        } else if (arg == "--warmup") {
            detector.glrt_warmup_samples = static_cast<int>(parseDouble(requireValue("--warmup"), "--warmup"));
        } else if (arg == "--reference-lat") {
            sim.reference_lat_deg = parseDouble(requireValue("--reference-lat"), "--reference-lat");
        } else if (arg == "--reference-lon") {
            sim.reference_lon_deg = parseDouble(requireValue("--reference-lon"), "--reference-lon");
        } else if (arg == "--reference-alt") {
            sim.reference_alt_m = parseDouble(requireValue("--reference-alt"), "--reference-alt");
        } else if (arg == "--no-uwb") {
            sim.enable_uwb = false;
        } else if (arg == "--no-flow") {
            sim.enable_optical_flow = false;
        } else if (arg == "--no-mag") {
            sim.enable_magnetometer = false;
        } else if (arg == "--help") {
            printHelp();
            return 0;
        } else {
            std::cerr << "Unknown option: " << arg << "\n";
            printHelp();
            return 2;
        }
    }

    if (sim.dt_s <= 0.0 || sim.duration_s <= 0.0) {
        std::cerr << "duration and dt must be positive\n";
        return 2;
    }
    if (attack.end_s <= attack.start_s) {
        std::cerr << "attack end must be greater than attack start\n";
        return 2;
    }
    if (attack.ramp_s < 0.0) {
        std::cerr << "attack ramp must be non-negative\n";
        return 2;
    }
    if (detector.consecutive_samples < 1 || detector.glrt_warmup_samples < 0) {
        std::cerr << "consecutive must be >= 1 and warmup must be >= 0\n";
        return 2;
    }

    Simulator simulator(sim, attack, detector);
    return simulator.run();
}
