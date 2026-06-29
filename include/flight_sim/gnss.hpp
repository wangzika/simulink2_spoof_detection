#pragma once

#include "flight_sim/state.hpp"

#include <unordered_map>
#include <vector>

namespace flight_sim {

struct GeodeticPosition {
    double lat_rad{0.0};
    double lon_rad{0.0};
    double alt_m{0.0};
};

struct AzElRange {
    double azimuth_rad{0.0};
    double elevation_rad{0.0};
    double range_m{0.0};
};

struct PseudorangePrediction {
    double predicted_pseudorange_m{0.0};
    double residual_m{0.0};
    double disturbance_estimate_m{0.0};
    double innovation_variance_m2{1.0};
};

double degToRad(double deg);
GeodeticPosition referenceGeodetic(const SimulationConfig& config);

Vec3 geodeticToEcef(const GeodeticPosition& lla);
Vec3 enuToEcef(const Vec3& enu_m, const GeodeticPosition& reference);
Vec3 ecefToEnu(const Vec3& ecef_m, const GeodeticPosition& reference);
Vec3 enuVectorToEcef(const Vec3& enu_m, const GeodeticPosition& reference);
Vec3 ecefVectorToEnu(const Vec3& ecef_m, const GeodeticPosition& reference);

AzElRange azElRange(
    const Vec3& receiver_ecef_m,
    const Vec3& satellite_ecef_m,
    const GeodeticPosition& reference);

SatelliteState satelliteStateFromEphemeris(const Ephemeris& eph, double t_s);
std::vector<Ephemeris> defaultGpsEphemerides();

double geometricPseudorange(const Vec3& receiver_ecef_m, const SatelliteState& satellite);
double chiSquareThresholdForFalseAlarm(double false_alarm_rate, int dof);

class LmsPseudorangeFilter {
public:
    LmsPseudorangeFilter(int order, double step_size);

    void reset();
    double update(int prn, double measurement_m);

private:
    struct Channel {
        std::vector<double> history;
        std::vector<double> weights;
        double last_measurement_m{0.0};
        double filtered_m{0.0};
        bool initialized{false};
    };

    int order_{5};
    double step_size_{0.08};
    std::unordered_map<int, Channel> channels_;
};

class EnhancedPseudorangePredictor {
public:
    void reset();

    PseudorangePrediction update(
        int prn,
        double t_s,
        double filtered_pseudorange_m,
        double geometric_pseudorange_m,
        double geometric_range_rate_mps,
        double measurement_variance_m2);

private:
    struct Channel {
        double bias_m{0.0};
        double drift_mps{0.0};
        double disturbance_m{0.0};
        double p[3][3]{{4.0, 0.0, 0.0}, {0.0, 1.0, 0.0}, {0.0, 0.0, 4.0}};
        double last_t_s{0.0};
        bool initialized{false};
    };

    std::unordered_map<int, Channel> channels_;
};

} // namespace flight_sim
