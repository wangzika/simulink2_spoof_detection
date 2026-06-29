#pragma once

namespace flight_sim {

struct InavParameters {
    // Naming follows the Simulink/PX4-style PARAM_INAV_* family where
    // possible. The generated project only exposes a small subset in C, so
    // this struct keeps the migration explicit and tunable in C++.
    double PARAM_INAV_W_XY_GPS_P{1.0};
    double PARAM_INAV_W_XY_GPS_V{1.0};
    double PARAM_INAV_W_Z_GPS_P{0.65};
    double PARAM_INAV_W_Z_BARO_P{1.25};
    double PARAM_INAV_W_XY_UWB_P{0.85};
    double PARAM_INAV_W_Z_UWB_P{0.35};
    double PARAM_INAV_W_XY_FLOW_V{0.75};
    double PARAM_INAV_W_YAW_MAG{0.035};
    double PARAM_INAV_W_ACC_BIAS{0.015};
    double PARAM_INAV_ACC_NOISE{0.35};
    double PARAM_INAV_GPS_P_NOISE{0.35};
    double PARAM_INAV_GPS_V_NOISE{0.16};
    double PARAM_INAV_BARO_NOISE{0.20};
    double PARAM_INAV_UWB_P_NOISE{0.18};
    double PARAM_INAV_FLOW_V_NOISE{0.12};
    double PARAM_INAV_MAG_YAW_NOISE{0.035};
    double PARAM_INAV_SONAR_ERR{0.30};
    double PARAM_INAV_GPS_GATE{4.0};
    double PARAM_INAV_RECOVERY_GATE{1.8};
    double PARAM_INAV_MAX_REJECT_S{3.0};
    double PARAM_INAV_REACQUIRE_S{1.5};

    static InavParameters defaults();
};

} // namespace flight_sim
