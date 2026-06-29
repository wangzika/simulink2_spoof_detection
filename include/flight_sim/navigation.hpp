#pragma once

#include "flight_sim/inav_parameters.hpp"
#include "flight_sim/state.hpp"

namespace flight_sim {

class MultiSensorNavigation {
public:
    MultiSensorNavigation(SimulationConfig config, InavParameters params = InavParameters::defaults());

    void reset(const DroneState& initial = {});
    void propagate(const SensorSample& sample);
    void correct(const SensorSample& sample, bool gps_trusted);

    const NavEstimate& estimate() const { return estimate_; }

private:
    struct AxisKalman {
        double pos{0.0};
        double vel{0.0};
        double bias{0.0};
        double p[3][3]{{1.0, 0.0, 0.0}, {0.0, 1.0, 0.0}, {0.0, 0.0, 0.2}};

        void reset(double pos0, double vel0);
        void predict(double accel_meas, double dt, double accel_noise, double bias_noise);
        void updatePosition(double measured_pos, double variance, double weight);
        void updateVelocity(double measured_vel, double variance, double weight);
        void updateScalar(double measured, const double h[3], double variance, double weight);
    };

    SimulationConfig config_;
    InavParameters params_;
    NavEstimate estimate_{};
    AxisKalman axis_[3]{};
    bool initialized_{false};
    double last_time_s_{0.0};

    void syncEstimateFromFilter();
};

} // namespace flight_sim
