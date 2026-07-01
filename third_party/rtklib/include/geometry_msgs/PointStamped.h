#pragma once

#include "ros/ros.h"

namespace geometry_msgs {

struct Point {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

struct PointStamped {
    struct Header {
        ros::Time stamp;
    } header;
    Point point;
};

}  // namespace geometry_msgs
