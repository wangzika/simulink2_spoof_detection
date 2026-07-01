#pragma once

#include <chrono>
#include <cstdio>
#include <string>
#include <thread>

namespace ros {

class Duration {
public:
    explicit Duration(double seconds = 0.0) : seconds_(seconds) {}
    double toSec() const { return seconds_; }
    void sleep() const
    {
        if (seconds_ > 0.0) {
            std::this_thread::sleep_for(std::chrono::duration<double>(seconds_));
        }
    }

private:
    double seconds_;
};

class WallDuration : public Duration {
public:
    explicit WallDuration(double seconds = 0.0) : Duration(seconds) {}
};

class Time {
public:
    Time() : seconds_(0.0) {}
    explicit Time(double seconds) : seconds_(seconds) {}
    static Time now() { return Time(0.0); }
    void fromSec(double seconds) { seconds_ = seconds; }
    double toSec() const { return seconds_; }
    bool isZero() const { return seconds_ == 0.0; }

private:
    double seconds_;
};

inline Duration operator-(const Time& lhs, const Time& rhs)
{
    return Duration(lhs.toSec() - rhs.toSec());
}

class WallTime {
public:
    WallTime() : point_(std::chrono::steady_clock::now()) {}
    static WallTime now() { return WallTime(); }

private:
    std::chrono::steady_clock::time_point point_;
    friend WallDuration operator-(const WallTime& lhs, const WallTime& rhs);
};

inline WallDuration operator-(const WallTime& lhs, const WallTime& rhs)
{
    return WallDuration(std::chrono::duration<double>(lhs.point_ - rhs.point_).count());
}

class Publisher {
public:
    template <typename T>
    void publish(const T&) const {}
};

class NodeHandle {
public:
    NodeHandle() = default;
    explicit NodeHandle(const std::string&) {}

    template <typename T>
    Publisher advertise(const std::string&, int)
    {
        return Publisher();
    }

    template <typename T>
    void param(const std::string&, T& value, const T& default_value) const
    {
        value = default_value;
    }

    template <typename T>
    bool getParam(const std::string&, T&) const
    {
        return false;
    }
};

inline void init(int&, char**, const std::string&) {}
inline bool ok() { return true; }
inline void spinOnce() {}

}  // namespace ros

#define ROS_INFO(...) do { std::fprintf(stderr, __VA_ARGS__); std::fprintf(stderr, "\n"); } while (0)
#define ROS_WARN_THROTTLE(rate, ...) do { (void)(rate); std::fprintf(stderr, __VA_ARGS__); std::fprintf(stderr, "\n"); } while (0)
#define ROS_ERROR(...) do { std::fprintf(stderr, __VA_ARGS__); std::fprintf(stderr, "\n"); } while (0)
