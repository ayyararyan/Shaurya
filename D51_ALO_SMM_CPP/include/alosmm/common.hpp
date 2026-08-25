#pragma once
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <mutex>
#include <optional>
#include <queue>
#include <random>
#include <sstream>
#include <span>
#include <ctime>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace alosmm {
using Clock = std::chrono::steady_clock;
using SysClock = std::chrono::system_clock;
using Ns = std::chrono::nanoseconds;
using Ms = std::chrono::milliseconds;

inline int64_t now_unix_ns() {
    return std::chrono::duration_cast<Ns>(SysClock::now().time_since_epoch()).count();
}
inline int64_t now_unix_ms() { return now_unix_ns() / 1'000'000; }
inline double ns_to_seconds(int64_t ns) { return static_cast<double>(ns) / 1e9; }
inline double clamp(double x, double lo, double hi) { return std::max(lo, std::min(hi, x)); }
inline bool finite(double x) { return std::isfinite(x); }
inline double floor_tick(double x, double tick) { return std::floor((x + 1e-12) / tick) * tick; }
inline double ceil_tick(double x, double tick) { return std::ceil((x - 1e-12) / tick) * tick; }
inline std::string env_or(std::string_view key, std::string fallback = {}) {
    if (const char* v = std::getenv(std::string(key).c_str())) return std::string(v);
    return fallback;
}
inline std::string iso_utc(int64_t unix_ns) {
    std::time_t tt = static_cast<std::time_t>(unix_ns / 1'000'000'000LL);
    std::tm tm{};
#if defined(_WIN32)
    gmtime_s(&tm, &tt);
#else
    gmtime_r(&tt, &tm);
#endif
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm);
    std::ostringstream os; os << buf << 'Z'; return os.str();
}
inline std::string utc_date(int64_t unix_ns = now_unix_ns()) {
    std::time_t tt = static_cast<std::time_t>(unix_ns / 1'000'000'000LL);
    std::tm tm{};
#if defined(_WIN32)
    gmtime_s(&tm, &tt);
#else
    gmtime_r(&tt, &tm);
#endif
    char buf[16]; std::strftime(buf, sizeof(buf), "%Y-%m-%d", &tm); return buf;
}

class Ewma {
public:
    explicit Ewma(double half_life_obs = 600.0)
      : alpha_(1.0 - std::exp(std::log(0.5) / std::max(1.0, half_life_obs))) {}
    void update(double x) { value_ = initialized_ ? (1.0-alpha_)*value_ + alpha_*x : x; initialized_=true; ++n_; }
    [[nodiscard]] double value(double fallback=0.0) const { return initialized_ ? value_ : fallback; }
    [[nodiscard]] uint64_t count() const { return n_; }
    void restore(double value, uint64_t n) { value_=value; n_=n; initialized_=n>0; }
private:
    double alpha_{}; double value_{}; bool initialized_{false}; uint64_t n_{0};
};

class RunningMoments {
public:
    void add(double x) { ++n_; const double d=x-mean_; mean_ += d/static_cast<double>(n_); m2_ += d*(x-mean_); }
    [[nodiscard]] uint64_t n() const { return n_; }
    [[nodiscard]] double mean() const { return mean_; }
    [[nodiscard]] double variance() const { return n_>1 ? m2_/static_cast<double>(n_-1) : 0.0; }
    [[nodiscard]] double stdev() const { return std::sqrt(std::max(0.0, variance())); }
private:
    uint64_t n_{0}; double mean_{0}; double m2_{0};
};
} // namespace alosmm
