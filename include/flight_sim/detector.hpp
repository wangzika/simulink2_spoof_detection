#pragma once

#include "flight_sim/gnss.hpp"
#include "flight_sim/state.hpp"

#include <array>

namespace flight_sim {

class GpsSpoofDetector {
public:
    GpsSpoofDetector(DetectorConfig detector_config, SimulationConfig sim_config);

    DetectionState update(
        const SensorSample& sample,
        const NavEstimate& predicted,
        const Vec3& attitude_error,
        const Vec3& body_rate,
        const Vec3& moment_command);

private:
    DetectorConfig detector_config_;
    SimulationConfig sim_config_;
    LmsPseudorangeFilter lms_filter_;
    EnhancedPseudorangePredictor pseudorange_predictor_;
    DetectionState last_state_{};
    int glrt_detection_count_{0};
    int gps_residual_count_{0};
    int pseudorange_update_count_{0};
    std::array<double, 6> observer_state_{};

    void updatePseudorangeGlrt(const SensorSample& sample, const NavEstimate& predicted, DetectionState& state);
    Vec3 updateDisturbanceObserver(
        const Vec3& attitude_error,
        const Vec3& body_rate,
        const Vec3& moment_command,
        double dt_s);
};

} // namespace flight_sim
