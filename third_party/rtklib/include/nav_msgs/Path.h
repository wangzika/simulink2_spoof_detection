#pragma once

#include <vector>
#include "geometry_msgs/PointStamped.h"
#include "ros/ros.h"

namespace nav_msgs {

struct Path {
    struct Header {
        ros::Time stamp;
    } header;
    std::vector<geometry_msgs::PointStamped> poses;
};

}  // namespace nav_msgs
