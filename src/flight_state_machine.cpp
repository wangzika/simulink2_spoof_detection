#include "flight_sim/flight_state_machine.hpp"

namespace flight_sim {

FlightStateMachine::FlightStateMachine(InavParameters params, SimulationConfig config)
    : params_(params), config_(config) {}

ModeDecision FlightStateMachine::update(double t_s, const SensorSample& sensor, const DetectionState& detection) {
    (void)sensor;

    if (t_s < 0.5) {
        setMode(FlightMode::Grounded, t_s);
    } else if (t_s < 4.0 && decision_.mode == FlightMode::Grounded) {
        setMode(FlightMode::Takeoff, t_s);
    } else if (t_s > 0.9 * config_.duration_s && decision_.mode != FlightMode::Landing) {
        setMode(FlightMode::Landing, t_s);
    }

    if (detection.gps_spoof_detected) {
        last_detection_time_s_ = t_s;
        if (decision_.mode != FlightMode::GpsRejected && decision_.mode != FlightMode::GpsSuspect) {
            setMode(FlightMode::GpsSuspect, t_s);
        }
    }

    switch (decision_.mode) {
    case FlightMode::Grounded:
        decision_.gps_trusted = true;
        break;
    case FlightMode::Takeoff:
        decision_.gps_trusted = true;
        if (t_s >= 4.0) {
            setMode(FlightMode::Mission, t_s);
        }
        break;
    case FlightMode::Mission:
        decision_.gps_trusted = true;
        break;
    case FlightMode::GpsSuspect:
        decision_.gps_trusted = true;
        if (t_s - mode_enter_time_s_ > 0.4) {
            setMode(FlightMode::GpsRejected, t_s);
        }
        break;
    case FlightMode::GpsRejected:
        decision_.gps_trusted = false;
        if (t_s - last_detection_time_s_ > params_.PARAM_INAV_REACQUIRE_S &&
            detection.gps_residual_norm_m < params_.PARAM_INAV_RECOVERY_GATE) {
            setMode(FlightMode::GpsReacquire, t_s);
        }
        break;
    case FlightMode::GpsReacquire:
        decision_.gps_trusted = true;
        if (detection.gps_residual_norm_m < params_.PARAM_INAV_RECOVERY_GATE &&
            t_s - mode_enter_time_s_ > params_.PARAM_INAV_REACQUIRE_S) {
            setMode(FlightMode::Mission, t_s);
        }
        break;
    case FlightMode::Landing:
        decision_.gps_trusted = true;
        break;
    }

    decision_.failsafe = (decision_.mode == FlightMode::GpsRejected);
    decision_.mode_name = modeName(decision_.mode);
    return decision_;
}

void FlightStateMachine::setMode(FlightMode mode, double t_s) {
    if (decision_.mode == mode) {
        return;
    }
    decision_.mode = mode;
    decision_.mode_name = modeName(mode);
    mode_enter_time_s_ = t_s;
}

std::string FlightStateMachine::modeName(FlightMode mode) {
    switch (mode) {
    case FlightMode::Grounded:
        return "Grounded";
    case FlightMode::Takeoff:
        return "Takeoff";
    case FlightMode::Mission:
        return "Mission";
    case FlightMode::GpsSuspect:
        return "GPS Suspect";
    case FlightMode::GpsRejected:
        return "GPS Rejected";
    case FlightMode::GpsReacquire:
        return "GPS Reacquire";
    case FlightMode::Landing:
        return "Landing";
    }
    return "Unknown";
}

} // namespace flight_sim
