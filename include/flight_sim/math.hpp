#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <ostream>

namespace flight_sim {

constexpr double kPi = 3.14159265358979323846;

struct Vec3 {
    double x{0.0};
    double y{0.0};
    double z{0.0};

    constexpr Vec3() = default;
    constexpr Vec3(double x_, double y_, double z_) : x(x_), y(y_), z(z_) {}

    Vec3 operator+(const Vec3& rhs) const { return {x + rhs.x, y + rhs.y, z + rhs.z}; }
    Vec3 operator-(const Vec3& rhs) const { return {x - rhs.x, y - rhs.y, z - rhs.z}; }
    Vec3 operator-() const { return {-x, -y, -z}; }
    Vec3 operator*(double s) const { return {x * s, y * s, z * s}; }
    Vec3 operator/(double s) const { return {x / s, y / s, z / s}; }

    Vec3& operator+=(const Vec3& rhs) {
        x += rhs.x;
        y += rhs.y;
        z += rhs.z;
        return *this;
    }

    Vec3& operator-=(const Vec3& rhs) {
        x -= rhs.x;
        y -= rhs.y;
        z -= rhs.z;
        return *this;
    }

    Vec3& operator*=(double s) {
        x *= s;
        y *= s;
        z *= s;
        return *this;
    }

    double normSquared() const { return x * x + y * y + z * z; }
    double norm() const { return std::sqrt(normSquared()); }

    Vec3 normalized(double eps = 1e-9) const {
        const double n = norm();
        if (n < eps) {
            return {};
        }
        return *this / n;
    }
};

inline Vec3 operator*(double s, const Vec3& v) { return v * s; }

inline double dot(const Vec3& a, const Vec3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

inline Vec3 cross(const Vec3& a, const Vec3& b) {
    return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
}

inline double clamp(double value, double lo, double hi) {
    return std::max(lo, std::min(value, hi));
}

inline Vec3 clampNorm(const Vec3& value, double maxNorm) {
    const double n = value.norm();
    if (n <= maxNorm || n < 1e-12) {
        return value;
    }
    return value * (maxNorm / n);
}

struct Mat3 {
    std::array<std::array<double, 3>, 3> m{{
        {{1.0, 0.0, 0.0}},
        {{0.0, 1.0, 0.0}},
        {{0.0, 0.0, 1.0}},
    }};

    Vec3 operator*(const Vec3& v) const {
        return {
            m[0][0] * v.x + m[0][1] * v.y + m[0][2] * v.z,
            m[1][0] * v.x + m[1][1] * v.y + m[1][2] * v.z,
            m[2][0] * v.x + m[2][1] * v.y + m[2][2] * v.z,
        };
    }

    Mat3 transpose() const {
        Mat3 out;
        for (int r = 0; r < 3; ++r) {
            for (int c = 0; c < 3; ++c) {
                out.m[r][c] = m[c][r];
            }
        }
        return out;
    }

    Vec3 col(int c) const { return {m[0][c], m[1][c], m[2][c]}; }

    static Mat3 fromColumns(const Vec3& c0, const Vec3& c1, const Vec3& c2) {
        Mat3 out;
        out.m[0][0] = c0.x;
        out.m[1][0] = c0.y;
        out.m[2][0] = c0.z;
        out.m[0][1] = c1.x;
        out.m[1][1] = c1.y;
        out.m[2][1] = c1.z;
        out.m[0][2] = c2.x;
        out.m[1][2] = c2.y;
        out.m[2][2] = c2.z;
        return out;
    }
};

struct Quaternion {
    double w{1.0};
    double x{0.0};
    double y{0.0};
    double z{0.0};

    Quaternion() = default;
    Quaternion(double w_, double x_, double y_, double z_) : w(w_), x(x_), y(y_), z(z_) {}

    Quaternion operator*(const Quaternion& rhs) const {
        return {
            w * rhs.w - x * rhs.x - y * rhs.y - z * rhs.z,
            w * rhs.x + x * rhs.w + y * rhs.z - z * rhs.y,
            w * rhs.y - x * rhs.z + y * rhs.w + z * rhs.x,
            w * rhs.z + x * rhs.y - y * rhs.x + z * rhs.w,
        };
    }

    Quaternion operator*(double s) const { return {w * s, x * s, y * s, z * s}; }

    Quaternion& normalize() {
        const double n = std::sqrt(w * w + x * x + y * y + z * z);
        if (n > 1e-12) {
            w /= n;
            x /= n;
            y /= n;
            z /= n;
        }
        return *this;
    }

    Mat3 toRotationMatrix() const {
        const double xx = x * x;
        const double yy = y * y;
        const double zz = z * z;
        const double xy = x * y;
        const double xz = x * z;
        const double yz = y * z;
        const double wx = w * x;
        const double wy = w * y;
        const double wz = w * z;

        Mat3 r;
        r.m[0][0] = 1.0 - 2.0 * (yy + zz);
        r.m[0][1] = 2.0 * (xy - wz);
        r.m[0][2] = 2.0 * (xz + wy);
        r.m[1][0] = 2.0 * (xy + wz);
        r.m[1][1] = 1.0 - 2.0 * (xx + zz);
        r.m[1][2] = 2.0 * (yz - wx);
        r.m[2][0] = 2.0 * (xz - wy);
        r.m[2][1] = 2.0 * (yz + wx);
        r.m[2][2] = 1.0 - 2.0 * (xx + yy);
        return r;
    }

    double yawRad() const {
        const Mat3 r = toRotationMatrix();
        return std::atan2(r.m[1][0], r.m[0][0]);
    }

    static Quaternion fromAxisAngle(const Vec3& axis, double angle_rad) {
        const Vec3 unit_axis = axis.normalized();
        const double half = 0.5 * angle_rad;
        const double s = std::sin(half);
        return {std::cos(half), unit_axis.x * s, unit_axis.y * s, unit_axis.z * s};
    }

    static Quaternion fromYaw(double yaw_rad) {
        return fromAxisAngle({0.0, 0.0, 1.0}, yaw_rad);
    }

    static Quaternion fromRotationMatrix(const Mat3& r) {
        const double trace = r.m[0][0] + r.m[1][1] + r.m[2][2];
        Quaternion q;
        if (trace > 0.0) {
            const double s = std::sqrt(trace + 1.0) * 2.0;
            q.w = 0.25 * s;
            q.x = (r.m[2][1] - r.m[1][2]) / s;
            q.y = (r.m[0][2] - r.m[2][0]) / s;
            q.z = (r.m[1][0] - r.m[0][1]) / s;
        } else if (r.m[0][0] > r.m[1][1] && r.m[0][0] > r.m[2][2]) {
            const double s = std::sqrt(1.0 + r.m[0][0] - r.m[1][1] - r.m[2][2]) * 2.0;
            q.w = (r.m[2][1] - r.m[1][2]) / s;
            q.x = 0.25 * s;
            q.y = (r.m[0][1] + r.m[1][0]) / s;
            q.z = (r.m[0][2] + r.m[2][0]) / s;
        } else if (r.m[1][1] > r.m[2][2]) {
            const double s = std::sqrt(1.0 + r.m[1][1] - r.m[0][0] - r.m[2][2]) * 2.0;
            q.w = (r.m[0][2] - r.m[2][0]) / s;
            q.x = (r.m[0][1] + r.m[1][0]) / s;
            q.y = 0.25 * s;
            q.z = (r.m[1][2] + r.m[2][1]) / s;
        } else {
            const double s = std::sqrt(1.0 + r.m[2][2] - r.m[0][0] - r.m[1][1]) * 2.0;
            q.w = (r.m[1][0] - r.m[0][1]) / s;
            q.x = (r.m[0][2] + r.m[2][0]) / s;
            q.y = (r.m[1][2] + r.m[2][1]) / s;
            q.z = 0.25 * s;
        }
        return q.normalize();
    }

    void integrateBodyRate(const Vec3& omega, double dt) {
        Quaternion omegaQ{0.0, omega.x, omega.y, omega.z};
        Quaternion qDot = (*this * omegaQ) * 0.5;
        w += qDot.w * dt;
        x += qDot.x * dt;
        y += qDot.y * dt;
        z += qDot.z * dt;
        normalize();
    }
};

inline std::ostream& operator<<(std::ostream& os, const Vec3& v) {
    os << v.x << "," << v.y << "," << v.z;
    return os;
}

} // namespace flight_sim
