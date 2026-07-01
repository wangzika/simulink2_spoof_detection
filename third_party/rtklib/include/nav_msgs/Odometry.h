#pragma once

#include <array>
#include "ros/ros.h"

namespace nav_msgs {

struct Header {
    ros::Time stamp;
};

struct Odometry {
    struct Position {
        double x = 0.0;
        double y = 0.0;
        double z = 0.0;
    };
    struct Orientation {
        double x = 0.0;
        double y = 0.0;
        double z = 0.0;
        double w = 1.0;
    };
    struct PoseData {
        Position position;
        Orientation orientation;
    };
    struct PoseWithCovariance {
        PoseData pose;
        std::array<double, 36> covariance{};
    };
    Header header;
    PoseWithCovariance pose;
};

}  // namespace nav_msgs
