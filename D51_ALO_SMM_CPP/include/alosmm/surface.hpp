#pragma once
#include "types.hpp"
namespace alosmm {
class SurfaceEngine {
public:
    explicit SurfaceEngine(double annual_rate=0.06):rate_(annual_rate){}
    SurfaceFit fit_leave_strike_out(const std::vector<Instrument>& instruments,const std::unordered_map<uint32_t,Book>& books,double exclude_strike,int64_t now_ns);
    double fair_option_price(const Instrument& inst,const SurfaceFit& fit,int64_t now_ns) const;
    Greeks greeks(const Instrument& inst,const SurfaceFit& fit,int64_t now_ns) const;
    static double ssvi_total_variance(double k,double theta,double rho,double phi);
    static double black_price(double F,double K,double T,double vol,bool call,double rate);
    static double implied_vol(double price,double F,double K,double T,bool call,double rate);
private:
    double rate_; std::optional<SurfaceFit> prev_;
};
} // namespace alosmm
