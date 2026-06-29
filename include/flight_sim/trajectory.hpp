#pragma once

#include "flight_sim/state.hpp"

#include <string>
#include <vector>

namespace flight_sim {

struct TrajectoryWaypoint {
    double time_s{0.0};
    Vec3 position_m{};
    double yaw_rad{0.0};
};

class TrajectoryPlanner {
public:
    bool setMode(const std::string& mode, std::string& error);
    bool loadWaypointCsv(const std::string& path, std::string& error);
    bool hasCustomWaypoints() const { return !waypoints_.empty(); }
    std::string modeName() const;

    TrajectorySetpoint sample(double t_s) const;

private:
    enum class Mode {
        Default,
        Hover,
        FigureEight,
    };

    Mode mode_{Mode::Default};
    std::vector<TrajectoryWaypoint> waypoints_{};

    TrajectorySetpoint sampleDefault(double t_s) const;
    TrajectorySetpoint sampleHover(double t_s) const;
    TrajectorySetpoint sampleFigureEight(double t_s) const;
    TrajectorySetpoint sampleWaypoints(double t_s) const;
};

} // namespace flight_sim
