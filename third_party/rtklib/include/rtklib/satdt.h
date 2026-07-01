#pragma once

#include <array>

namespace rtklib {

struct satdt {
    std::array<double, 3> pos{};
    std::array<double, 3> vel{};
    double clk_bias = 0.0;
    double clk_drift = 0.0;
};

}  // namespace rtklib
