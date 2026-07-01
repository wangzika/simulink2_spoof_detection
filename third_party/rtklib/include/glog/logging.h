#pragma once

#include <iostream>

#define INFO 0
#define WARNING 1
#define ERROR 2
#define FATAL 3
#define LOG(level) std::cerr

namespace google {
inline void InitGoogleLogging(const char*) {}
}
