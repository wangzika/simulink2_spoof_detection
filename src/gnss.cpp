#include "flight_sim/gnss.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace flight_sim {

namespace {

constexpr double kWgs84A = 6378137.0;
constexpr double kWgs84F = 1.0 / 298.257223563;
constexpr double kWgs84E2 = kWgs84F * (2.0 - kWgs84F);
constexpr double kEarthRotationRadps = 7.2921151467e-5;
constexpr double kGpsMu = 3.986005e14;

double wrapAngle(double angle_rad) {
    double wrapped = std::fmod(angle_rad, 2.0 * kPi);
    if (wrapped < 0.0) {
        wrapped += 2.0 * kPi;
    }
    return wrapped;
}

double solveKepler(double mean_anomaly_rad, double eccentricity) {
    double eccentric_anomaly = mean_anomaly_rad;
    for (int i = 0; i < 12; ++i) {
        const double f = eccentric_anomaly - eccentricity * std::sin(eccentric_anomaly) - mean_anomaly_rad;
        const double fp = 1.0 - eccentricity * std::cos(eccentric_anomaly);
        if (std::abs(fp) < 1e-12) {
            break;
        }
        const double step = f / fp;
        eccentric_anomaly -= step;
        if (std::abs(step) < 1e-12) {
            break;
        }
    }
    return eccentric_anomaly;
}

Vec3 satellitePositionFromEphemeris(const Ephemeris& eph, double t_s) {
    const double tk = t_s - eph.epoch_s;
    const double a = eph.semi_major_axis_m;
    const double n0 = std::sqrt(kGpsMu / (a * a * a));
    const double mean_anomaly = wrapAngle(eph.mean_anomaly_rad + (n0 + eph.delta_mean_motion_radps) * tk);
    const double eccentric_anomaly = solveKepler(mean_anomaly, eph.eccentricity);
    const double sin_e = std::sin(eccentric_anomaly);
    const double cos_e = std::cos(eccentric_anomaly);
    const double true_anomaly = std::atan2(
        std::sqrt(std::max(0.0, 1.0 - eph.eccentricity * eph.eccentricity)) * sin_e,
        cos_e - eph.eccentricity);
    const double argument_latitude = true_anomaly + eph.argument_of_perigee_rad;
    const double radius = a * (1.0 - eph.eccentricity * cos_e);
    const double x_orb = radius * std::cos(argument_latitude);
    const double y_orb = radius * std::sin(argument_latitude);
    const double raan = eph.raan_rad - kEarthRotationRadps * tk;

    const double cos_o = std::cos(raan);
    const double sin_o = std::sin(raan);
    const double cos_i = std::cos(eph.inclination_rad);
    const double sin_i = std::sin(eph.inclination_rad);

    return {
        x_orb * cos_o - y_orb * cos_i * sin_o,
        x_orb * sin_o + y_orb * cos_i * cos_o,
        y_orb * sin_i,
    };
}

Vec3 eastAxis(double lon_rad) {
    return {-std::sin(lon_rad), std::cos(lon_rad), 0.0};
}

Vec3 northAxis(double lat_rad, double lon_rad) {
    return {
        -std::sin(lat_rad) * std::cos(lon_rad),
        -std::sin(lat_rad) * std::sin(lon_rad),
        std::cos(lat_rad),
    };
}

Vec3 upAxis(double lat_rad, double lon_rad) {
    return {
        std::cos(lat_rad) * std::cos(lon_rad),
        std::cos(lat_rad) * std::sin(lon_rad),
        std::sin(lat_rad),
    };
}

double regularizedGammaP(double a, double x) {
    if (x <= 0.0) {
        return 0.0;
    }
    if (a <= 0.0) {
        return 0.0;
    }

    constexpr int kMaxIterations = 200;
    constexpr double kEps = 3e-14;
    constexpr double kFpMin = std::numeric_limits<double>::min() / kEps;

    if (x < a + 1.0) {
        double ap = a;
        double sum = 1.0 / a;
        double del = sum;
        for (int n = 1; n <= kMaxIterations; ++n) {
            ++ap;
            del *= x / ap;
            sum += del;
            if (std::abs(del) < std::abs(sum) * kEps) {
                break;
            }
        }
        return sum * std::exp(-x + a * std::log(x) - std::lgamma(a));
    }

    double b = x + 1.0 - a;
    double c = 1.0 / kFpMin;
    double d = 1.0 / std::max(std::abs(b), kFpMin);
    if (b < 0.0) {
        d = -d;
    }
    double h = d;

    for (int i = 1; i <= kMaxIterations; ++i) {
        const double an = -static_cast<double>(i) * (static_cast<double>(i) - a);
        b += 2.0;
        d = an * d + b;
        if (std::abs(d) < kFpMin) {
            d = kFpMin;
        }
        c = b + an / c;
        if (std::abs(c) < kFpMin) {
            c = kFpMin;
        }
        d = 1.0 / d;
        const double del = d * c;
        h *= del;
        if (std::abs(del - 1.0) < kEps) {
            break;
        }
    }

    const double q = std::exp(-x + a * std::log(x) - std::lgamma(a)) * h;
    return clamp(1.0 - q, 0.0, 1.0);
}

double chiSquareCdf(double x, int dof) {
    if (dof <= 0) {
        return 0.0;
    }
    return regularizedGammaP(0.5 * static_cast<double>(dof), 0.5 * x);
}

void multiply3x3(const double a[3][3], const double b[3][3], double out[3][3]) {
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            out[r][c] = 0.0;
            for (int k = 0; k < 3; ++k) {
                out[r][c] += a[r][k] * b[k][c];
            }
        }
    }
}

} // namespace

double degToRad(double deg) {
    return deg * kPi / 180.0;
}

GeodeticPosition referenceGeodetic(const SimulationConfig& config) {
    return {degToRad(config.reference_lat_deg), degToRad(config.reference_lon_deg), config.reference_alt_m};
}

Vec3 geodeticToEcef(const GeodeticPosition& lla) {
    const double sin_lat = std::sin(lla.lat_rad);
    const double cos_lat = std::cos(lla.lat_rad);
    const double sin_lon = std::sin(lla.lon_rad);
    const double cos_lon = std::cos(lla.lon_rad);
    const double n = kWgs84A / std::sqrt(1.0 - kWgs84E2 * sin_lat * sin_lat);
    return {
        (n + lla.alt_m) * cos_lat * cos_lon,
        (n + lla.alt_m) * cos_lat * sin_lon,
        (n * (1.0 - kWgs84E2) + lla.alt_m) * sin_lat,
    };
}

Vec3 enuVectorToEcef(const Vec3& enu_m, const GeodeticPosition& reference) {
    return eastAxis(reference.lon_rad) * enu_m.x +
           northAxis(reference.lat_rad, reference.lon_rad) * enu_m.y +
           upAxis(reference.lat_rad, reference.lon_rad) * enu_m.z;
}

Vec3 ecefVectorToEnu(const Vec3& ecef_m, const GeodeticPosition& reference) {
    const Vec3 east = eastAxis(reference.lon_rad);
    const Vec3 north = northAxis(reference.lat_rad, reference.lon_rad);
    const Vec3 up = upAxis(reference.lat_rad, reference.lon_rad);
    return {dot(east, ecef_m), dot(north, ecef_m), dot(up, ecef_m)};
}

Vec3 enuToEcef(const Vec3& enu_m, const GeodeticPosition& reference) {
    return geodeticToEcef(reference) + enuVectorToEcef(enu_m, reference);
}

Vec3 ecefToEnu(const Vec3& ecef_m, const GeodeticPosition& reference) {
    return ecefVectorToEnu(ecef_m - geodeticToEcef(reference), reference);
}

AzElRange azElRange(
    const Vec3& receiver_ecef_m,
    const Vec3& satellite_ecef_m,
    const GeodeticPosition& reference) {
    const Vec3 los_enu = ecefVectorToEnu(satellite_ecef_m - receiver_ecef_m, reference);
    const double range = std::max(los_enu.norm(), 1e-9);
    double azimuth = std::atan2(los_enu.x, los_enu.y);
    if (azimuth < 0.0) {
        azimuth += 2.0 * kPi;
    }
    const double elevation = std::asin(clamp(los_enu.z / range, -1.0, 1.0));
    return {azimuth, elevation, range};
}

SatelliteState satelliteStateFromEphemeris(const Ephemeris& eph, double t_s) {
    constexpr double kVelocityStepS = 0.5;
    const Vec3 pos = satellitePositionFromEphemeris(eph, t_s);
    const Vec3 before = satellitePositionFromEphemeris(eph, t_s - kVelocityStepS);
    const Vec3 after = satellitePositionFromEphemeris(eph, t_s + kVelocityStepS);
    const double tk = t_s - eph.epoch_s;
    return {
        eph.prn,
        t_s,
        pos,
        (after - before) / (2.0 * kVelocityStepS),
        eph.clock_bias_m + eph.clock_drift_mps * tk,
        eph.clock_drift_mps,
    };
}

std::vector<Ephemeris> defaultGpsEphemerides() {
    const double incl = degToRad(55.0);
    return {
        {1, 26560000.0, 0.010, incl, degToRad(35.0), degToRad(12.0), degToRad(15.0), 0.0, 0.0, 1.4, 0.0001},
        {3, 26559000.0, 0.008, incl, degToRad(95.0), degToRad(48.0), degToRad(85.0), 0.0, 0.0, -0.8, -0.0001},
        {6, 26561000.0, 0.012, incl, degToRad(155.0), degToRad(84.0), degToRad(140.0), 0.0, 0.0, 0.6, 0.0002},
        {9, 26558000.0, 0.006, incl, degToRad(215.0), degToRad(120.0), degToRad(205.0), 0.0, 0.0, -1.1, 0.0001},
        {14, 26562000.0, 0.011, incl, degToRad(275.0), degToRad(156.0), degToRad(260.0), 0.0, 0.0, 0.9, -0.0002},
        {18, 26557000.0, 0.009, incl, degToRad(335.0), degToRad(192.0), degToRad(315.0), 0.0, 0.0, -0.4, 0.0001},
        {22, 26560500.0, 0.007, incl, degToRad(70.0), degToRad(228.0), degToRad(235.0), 0.0, 0.0, 1.1, 0.0001},
        {27, 26561500.0, 0.010, incl, degToRad(250.0), degToRad(300.0), degToRad(40.0), 0.0, 0.0, -0.7, -0.0001},
    };
}

double geometricPseudorange(const Vec3& receiver_ecef_m, const SatelliteState& satellite) {
    return (satellite.ecef_position_m - receiver_ecef_m).norm() - satellite.clock_bias_m;
}

double chiSquareThresholdForFalseAlarm(double false_alarm_rate, int dof) {
    if (dof <= 0) {
        return 0.0;
    }
    const double alpha = clamp(false_alarm_rate, 1e-12, 0.5);
    const double target = 1.0 - alpha;
    double lo = 0.0;
    double hi = std::max(1.0, static_cast<double>(dof));
    while (chiSquareCdf(hi, dof) < target && hi < 1e6) {
        hi *= 2.0;
    }
    for (int i = 0; i < 90; ++i) {
        const double mid = 0.5 * (lo + hi);
        if (chiSquareCdf(mid, dof) < target) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    return hi;
}

LmsPseudorangeFilter::LmsPseudorangeFilter(int order, double step_size)
    : order_(std::max(2, order)), step_size_(clamp(step_size, 0.0, 1.0)) {}

void LmsPseudorangeFilter::reset() {
    channels_.clear();
}

double LmsPseudorangeFilter::update(int prn, double measurement_m) {
    Channel& channel = channels_[prn];
    if (!channel.initialized) {
        channel.history.assign(static_cast<std::size_t>(order_), 0.0);
        channel.weights.assign(static_cast<std::size_t>(order_), 1.0 / static_cast<double>(order_));
        channel.last_measurement_m = measurement_m;
        channel.filtered_m = measurement_m;
        channel.initialized = true;
        return measurement_m;
    }

    const double delta = measurement_m - channel.last_measurement_m;
    for (int i = order_ - 1; i > 0; --i) {
        channel.history[static_cast<std::size_t>(i)] = channel.history[static_cast<std::size_t>(i - 1)];
    }
    channel.history[0] = delta;

    double predicted_delta = 0.0;
    double norm = 1e-6;
    for (int i = 0; i < order_; ++i) {
        predicted_delta += channel.weights[static_cast<std::size_t>(i)] * channel.history[static_cast<std::size_t>(i)];
        norm += channel.history[static_cast<std::size_t>(i)] * channel.history[static_cast<std::size_t>(i)];
    }

    const double error = delta - predicted_delta;
    for (int i = 0; i < order_; ++i) {
        channel.weights[static_cast<std::size_t>(i)] +=
            step_size_ * error * channel.history[static_cast<std::size_t>(i)] / norm;
    }

    double weight_sum = 0.0;
    for (double weight : channel.weights) {
        weight_sum += weight;
    }
    if (std::abs(weight_sum) > 1e-6) {
        for (double& weight : channel.weights) {
            weight /= weight_sum;
        }
    }

    double corrected_delta = 0.0;
    for (int i = 0; i < order_; ++i) {
        corrected_delta += channel.weights[static_cast<std::size_t>(i)] * channel.history[static_cast<std::size_t>(i)];
    }
    channel.filtered_m += corrected_delta + 0.35 * (delta - corrected_delta);
    channel.last_measurement_m = measurement_m;
    return channel.filtered_m;
}

void EnhancedPseudorangePredictor::reset() {
    channels_.clear();
}

PseudorangePrediction EnhancedPseudorangePredictor::update(
    int prn,
    double t_s,
    double filtered_pseudorange_m,
    double geometric_pseudorange_m,
    double geometric_range_rate_mps,
    double measurement_variance_m2) {
    Channel& channel = channels_[prn];
    const double observed_delay = filtered_pseudorange_m - geometric_pseudorange_m;
    if (!channel.initialized) {
        channel.bias_m = observed_delay;
        channel.drift_mps = geometric_range_rate_mps * 0.0;
        channel.disturbance_m = 0.0;
        channel.last_t_s = t_s;
        channel.initialized = true;
        return {filtered_pseudorange_m, 0.0, 0.0, measurement_variance_m2};
    }

    const double dt = clamp(t_s - channel.last_t_s, 1e-3, 1.0);
    channel.last_t_s = t_s;
    const double disturbance_decay = std::exp(-dt / 4.0);

    const double f[3][3]{
        {1.0, dt, 0.0},
        {0.0, 1.0, 0.0},
        {0.0, 0.0, disturbance_decay},
    };

    const double x_pred[3]{
        channel.bias_m + channel.drift_mps * dt,
        channel.drift_mps,
        channel.disturbance_m * disturbance_decay,
    };

    double fp[3][3]{};
    multiply3x3(f, channel.p, fp);

    double ft[3][3]{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            ft[r][c] = f[c][r];
        }
    }

    double p_pred[3][3]{};
    multiply3x3(fp, ft, p_pred);
    p_pred[0][0] += 0.01 * dt;
    p_pred[1][1] += 0.004 * dt;
    p_pred[2][2] += 0.03 * dt;

    const double h[3]{1.0, 0.0, 1.0};
    double ph[3]{};
    for (int r = 0; r < 3; ++r) {
        ph[r] = p_pred[r][0] * h[0] + p_pred[r][1] * h[1] + p_pred[r][2] * h[2];
    }
    const double variance = std::max(1e-6, measurement_variance_m2);
    const double s = h[0] * ph[0] + h[1] * ph[1] + h[2] * ph[2] + variance;
    const double predicted_delay = h[0] * x_pred[0] + h[1] * x_pred[1] + h[2] * x_pred[2];
    const double residual = observed_delay - predicted_delay;
    const double k[3]{ph[0] / s, ph[1] / s, ph[2] / s};

    channel.bias_m = x_pred[0] + k[0] * residual;
    channel.drift_mps = x_pred[1] + k[1] * residual;
    channel.disturbance_m = x_pred[2] + k[2] * residual;

    double kh[3][3]{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            kh[r][c] = k[r] * h[c];
        }
    }

    double i_minus_kh[3][3]{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            i_minus_kh[r][c] = (r == c ? 1.0 : 0.0) - kh[r][c];
        }
    }

    double next_p[3][3]{};
    multiply3x3(i_minus_kh, p_pred, next_p);
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            channel.p[r][c] = 0.5 * (next_p[r][c] + next_p[c][r]);
        }
    }

    return {
        geometric_pseudorange_m + predicted_delay,
        residual,
        channel.disturbance_m,
        s,
    };
}

} // namespace flight_sim
