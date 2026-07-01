#pragma once

#include <array>
#include <vector>
#include "ros/ros.h"
#include "rtklib/GNSS_Info_SD.h"
#include "rtklib/GNSS_Info_ZD.h"

namespace rtklib {

struct Header {
    ros::Time stamp;
};

struct GNSS_Info {
    Header header;
    std::array<double, 3> pos{};
    std::array<double, 3> vel{};
    std::array<double, 6> dtr{};
    std::array<double, 3> base_pos{};
    std::vector<GNSS_Info_ZD> ZD_Infos;
    std::vector<GNSS_Info_SD> SD_Infos;
    double weekSec = 0.0;
    int gpsWeek = 0;
    int stat = 0;
    int ns = 0;
    double age = 0.0;
    double ratio = 0.0;
    double thres = 0.0;
    std::array<double, 4> dop{};
    std::vector<double> amb;
    std::array<double, 6> var{};
    std::array<double, 6> velvar{};
};

}  // namespace rtklib
