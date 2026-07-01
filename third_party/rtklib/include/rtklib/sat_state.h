#pragma once

#include <array>
#include <cstdint>

namespace rtklib {

struct sat_state {
    int sys = 0;
    int vs = 0;
    std::array<double, 2> azel{};
    std::array<double, 2> azel_b{};
    std::array<double, 3> resp{};
    std::array<double, 3> resc{};
    std::array<double, 3> resd{};
    std::array<double, 3> icbias{};
    std::array<uint8_t, 3> vsat{};
    std::array<uint8_t, 3> vsatL{};
    std::array<uint8_t, 3> vsatP{};
    std::array<uint8_t, 3> vsatD{};
    std::array<uint16_t, 3> snr_rover{};
    std::array<uint16_t, 3> snr_base{};
    std::array<uint8_t, 3> fix{};
    std::array<uint8_t, 3> slip{};
    std::array<uint8_t, 3> half{};
    std::array<int, 3> outc{};
    std::array<int, 3> slipc{};
    std::array<int, 3> rejc{};
    std::array<double, 2> gf{};
    std::array<int, 2> mw{};
    double phw = 0.0;
    std::array<double, 6> pt{};
    std::array<double, 6> ph{};
    std::array<double, 3> P_COR{};
    std::array<double, 3> tgd{};
    std::array<int, 3> init{};
    std::array<int, 9> outlier_obs{};
    std::array<double, 3> lam{};
    std::array<int, 3> amb_id{};
    double ephvar = 0.0;
    int svh = 0;
    std::array<double, 3> dion{};
    std::array<double, 3> dtrp{};
};

}  // namespace rtklib
