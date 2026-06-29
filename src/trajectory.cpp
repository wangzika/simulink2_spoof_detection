#include "flight_sim/trajectory.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <sstream>

namespace flight_sim {
namespace {

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
            fields.push_back(trim(field));
            field.clear();
        } else {
            field.push_back(c);
        }
    }
    fields.push_back(trim(field));
    return fields;
}

bool parseDouble(const std::string& text, double& out) {
    char* end = nullptr;
    out = std::strtod(text.c_str(), &end);
    return end != text.c_str() && *end == '\0';
}

bool looksLikeHeader(const std::vector<std::string>& fields) {
    for (const std::string& field : fields) {
        for (char c : field) {
            if (std::isalpha(static_cast<unsigned char>(c))) {
                return true;
            }
        }
    }
    return false;
}

double smoothStep(double tau) {
    return tau * tau * tau * (10.0 + tau * (-15.0 + 6.0 * tau));
}

double smoothStepDerivative(double tau) {
    return 30.0 * tau * tau * (1.0 - tau) * (1.0 - tau);
}

double smoothStepSecondDerivative(double tau) {
    return 60.0 * tau * (1.0 - tau) * (1.0 - 2.0 * tau);
}

double wrapAngleDelta(double from_rad, double to_rad) {
    double delta = to_rad - from_rad;
    while (delta > kPi) {
        delta -= 2.0 * kPi;
    }
    while (delta < -kPi) {
        delta += 2.0 * kPi;
    }
    return delta;
}

TrajectorySetpoint makeTakeoffHover(double t_s, const Vec3& target_m, double yaw_rad) {
    TrajectorySetpoint ref;
    if (t_s < 4.0) {
        const double tau = clamp(t_s / 4.0, 0.0, 1.0);
        const double s = smoothStep(tau);
        const double sd = smoothStepDerivative(tau) / 4.0;
        const double sdd = smoothStepSecondDerivative(tau) / (4.0 * 4.0);
        ref.position_m = target_m * s;
        ref.velocity_mps = target_m * sd;
        ref.acceleration_mps2 = target_m * sdd;
        ref.yaw_rad = yaw_rad * s;
        return ref;
    }

    ref.position_m = target_m;
    ref.yaw_rad = yaw_rad;
    return ref;
}

} // namespace

bool TrajectoryPlanner::setMode(const std::string& mode, std::string& error) {
    const std::string value = lower(trim(mode));
    if (value.empty() || value == "default" || value == "mission" || value == "circle") {
        mode_ = Mode::Default;
        return true;
    }
    if (value == "hover") {
        mode_ = Mode::Hover;
        return true;
    }
    if (value == "figure8" || value == "figure-eight" || value == "eight") {
        mode_ = Mode::FigureEight;
        return true;
    }

    error = "unknown trajectory mode '" + mode + "'; expected default, hover, or figure8";
    return false;
}

bool TrajectoryPlanner::loadWaypointCsv(const std::string& path, std::string& error) {
    std::ifstream in(path);
    if (!in) {
        error = "failed to open trajectory waypoint CSV: " + path;
        return false;
    }

    std::vector<TrajectoryWaypoint> loaded;
    std::string line;
    int line_number = 0;
    bool header_checked = false;

    while (std::getline(in, line)) {
        ++line_number;
        const std::string cleaned = trim(line);
        if (cleaned.empty() || cleaned[0] == '#') {
            continue;
        }

        const auto fields = splitCsvLine(cleaned);
        if (!header_checked) {
            header_checked = true;
            if (looksLikeHeader(fields)) {
                continue;
            }
        }

        if (fields.size() < 4 || fields.size() > 5) {
            error = "trajectory CSV line " + std::to_string(line_number) +
                    " must contain time_s,x,y,z[,yaw_rad]";
            return false;
        }

        TrajectoryWaypoint waypoint;
        if (!parseDouble(fields[0], waypoint.time_s) ||
            !parseDouble(fields[1], waypoint.position_m.x) ||
            !parseDouble(fields[2], waypoint.position_m.y) ||
            !parseDouble(fields[3], waypoint.position_m.z)) {
            error = "trajectory CSV line " + std::to_string(line_number) + " contains a non-numeric field";
            return false;
        }
        if (fields.size() == 5 && !fields[4].empty()) {
            if (!parseDouble(fields[4], waypoint.yaw_rad)) {
                error = "trajectory CSV line " + std::to_string(line_number) + " contains a non-numeric yaw";
                return false;
            }
        }

        if (!loaded.empty() && waypoint.time_s <= loaded.back().time_s) {
            error = "trajectory CSV times must be strictly increasing; check line " + std::to_string(line_number);
            return false;
        }
        if (waypoint.time_s < 0.0) {
            error = "trajectory CSV time must be non-negative; check line " + std::to_string(line_number);
            return false;
        }
        loaded.push_back(waypoint);
    }

    if (loaded.empty()) {
        error = "trajectory CSV has no waypoints: " + path;
        return false;
    }

    waypoints_ = std::move(loaded);
    return true;
}

std::string TrajectoryPlanner::modeName() const {
    if (!waypoints_.empty()) {
        return "waypoints";
    }
    switch (mode_) {
    case Mode::Default:
        return "default";
    case Mode::Hover:
        return "hover";
    case Mode::FigureEight:
        return "figure8";
    }
    return "unknown";
}

TrajectorySetpoint TrajectoryPlanner::sample(double t_s) const {
    if (!waypoints_.empty()) {
        return sampleWaypoints(t_s);
    }
    switch (mode_) {
    case Mode::Default:
        return sampleDefault(t_s);
    case Mode::Hover:
        return sampleHover(t_s);
    case Mode::FigureEight:
        return sampleFigureEight(t_s);
    }
    return sampleDefault(t_s);
}

TrajectorySetpoint TrajectoryPlanner::sampleDefault(double t_s) const {
    TrajectorySetpoint ref;

    if (t_s < 4.0) {
        const double a = t_s / 4.0;
        ref.position_m = {0.0, 0.0, 1.8 * a};
        ref.velocity_mps = {0.0, 0.0, 1.8 / 4.0};
        ref.yaw_rad = 0.0;
        return ref;
    }

    const double radius = 3.0;
    const double cruise_altitude = 1.8;
    if (t_s < 8.0) {
        const double tau = (t_s - 4.0) / 4.0;
        const double smooth = smoothStep(tau);
        const double smooth_dot = smoothStepDerivative(tau) / 4.0;
        const double smooth_ddot = smoothStepSecondDerivative(tau) / (4.0 * 4.0);
        ref.position_m = {radius * smooth, 0.0, cruise_altitude};
        ref.velocity_mps = {radius * smooth_dot, 0.0, 0.0};
        ref.acceleration_mps2 = {radius * smooth_ddot, 0.0, 0.0};
        ref.yaw_rad = 0.0;
        return ref;
    }

    const double t = t_s - 8.0;
    const double omega = 0.08;
    const double z = cruise_altitude + 0.35 * std::sin(0.08 * t);
    const double angle = omega * t;

    ref.position_m = {
        radius * std::cos(angle),
        radius * std::sin(angle),
        z,
    };
    ref.velocity_mps = {
        -radius * omega * std::sin(angle),
        radius * omega * std::cos(angle),
        0.35 * 0.08 * std::cos(0.08 * t),
    };
    ref.acceleration_mps2 = {
        -radius * omega * omega * std::cos(angle),
        -radius * omega * omega * std::sin(angle),
        -0.35 * 0.08 * 0.08 * std::sin(0.08 * t),
    };
    ref.yaw_rad = angle;
    return ref;
}

TrajectorySetpoint TrajectoryPlanner::sampleHover(double t_s) const {
    return makeTakeoffHover(t_s, {0.0, 0.0, 1.8}, 0.0);
}

TrajectorySetpoint TrajectoryPlanner::sampleFigureEight(double t_s) const {
    if (t_s < 6.0) {
        return makeTakeoffHover(t_s * (4.0 / 6.0), {0.0, 0.0, 1.8}, 0.0);
    }

    const double t = t_s - 6.0;
    const double radius = 2.4;
    const double omega = 0.10;
    const double altitude = 1.8 + 0.25 * std::sin(0.06 * t);
    const double a = omega * t;

    TrajectorySetpoint ref;
    ref.position_m = {
        radius * std::sin(a),
        radius * std::sin(a) * std::cos(a),
        altitude,
    };
    ref.velocity_mps = {
        radius * omega * std::cos(a),
        radius * omega * std::cos(2.0 * a),
        0.25 * 0.06 * std::cos(0.06 * t),
    };
    ref.acceleration_mps2 = {
        -radius * omega * omega * std::sin(a),
        -2.0 * radius * omega * omega * std::sin(2.0 * a),
        -0.25 * 0.06 * 0.06 * std::sin(0.06 * t),
    };
    ref.yaw_rad = std::atan2(ref.velocity_mps.y, ref.velocity_mps.x);
    return ref;
}

TrajectorySetpoint TrajectoryPlanner::sampleWaypoints(double t_s) const {
    if (waypoints_.empty()) {
        return sampleDefault(t_s);
    }

    if (t_s <= waypoints_.front().time_s || waypoints_.size() == 1) {
        TrajectorySetpoint ref;
        ref.position_m = waypoints_.front().position_m;
        ref.yaw_rad = waypoints_.front().yaw_rad;
        return ref;
    }

    if (t_s >= waypoints_.back().time_s) {
        TrajectorySetpoint ref;
        ref.position_m = waypoints_.back().position_m;
        ref.yaw_rad = waypoints_.back().yaw_rad;
        return ref;
    }

    const auto next_it = std::upper_bound(
        waypoints_.begin(),
        waypoints_.end(),
        t_s,
        [](double t, const TrajectoryWaypoint& waypoint) {
            return t < waypoint.time_s;
        });
    const TrajectoryWaypoint& b = *next_it;
    const TrajectoryWaypoint& a = *(next_it - 1);
    const double duration = std::max(1e-6, b.time_s - a.time_s);
    const double tau = clamp((t_s - a.time_s) / duration, 0.0, 1.0);
    const double s = smoothStep(tau);
    const double sd = smoothStepDerivative(tau) / duration;
    const double sdd = smoothStepSecondDerivative(tau) / (duration * duration);
    const Vec3 delta = b.position_m - a.position_m;
    const double yaw_delta = wrapAngleDelta(a.yaw_rad, b.yaw_rad);

    TrajectorySetpoint ref;
    ref.position_m = a.position_m + delta * s;
    ref.velocity_mps = delta * sd;
    ref.acceleration_mps2 = delta * sdd;
    ref.yaw_rad = a.yaw_rad + yaw_delta * s;
    return ref;
}

} // namespace flight_sim
