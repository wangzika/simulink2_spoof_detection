#pragma once

#include <array>
#include <cstdint>

namespace rtklib {

struct obsdt {
    double time = 0.0;
    int sat = 0;
    int rcv = 0;
    std::array<uint16_t, 3> SNR{};
    std::array<uint8_t, 3> LLI{};
    std::array<uint8_t, 3> code{};
    std::array<double, 3> L{};
    std::array<double, 3> P{};
    std::array<double, 3> D{};
    int timevalid = 0;
    double eventime = 0.0;
    std::array<uint8_t, 3> Lstd{};
    std::array<uint8_t, 3> Pstd{};
    int freq = 0;
};

}  // namespace rtklib
