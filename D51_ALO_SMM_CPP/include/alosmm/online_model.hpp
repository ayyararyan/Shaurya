#pragma once
#include "config.hpp"
namespace alosmm {
constexpr size_t kFeatureCount=20;
struct FeatureVector { std::array<double,kFeatureCount> x{}; };
FeatureVector make_features(const FeatureState& s, double offset, Side side);

class OnlineStandardizer {
public:
    FeatureVector transform_and_update(const FeatureVector& raw, bool update);
    void save(std::ostream& os) const; void load(std::istream& is);
private:
    std::array<uint64_t,kFeatureCount> n_{}; std::array<double,kFeatureCount> mean_{}; std::array<double,kFeatureCount> m2_{};
};

class LogisticSGD {
public:
    LogisticSGD(double lr=.003,double l2=.0001):lr_(lr),l2_(l2){}
    double predict(const FeatureVector& x) const;
    void update(const FeatureVector& x, double y);
    void save(std::ostream& os) const; void load(std::istream& is);
private: std::array<double,kFeatureCount> w_{}; double b_{-4.0}; double lr_,l2_;
};

class LinearSGD {
public:
    LinearSGD(double lr=.003,double l2=.0001):lr_(lr),l2_(l2){}
    double predict(const FeatureVector& x) const;
    void update(const FeatureVector& x,double y,double weight=1.0);
    void save(std::ostream& os) const; void load(std::istream& is);
private: std::array<double,kFeatureCount> w_{}; double b_{0}; double lr_,l2_;
};

struct ActionModel {
    OnlineStandardizer scale; LogisticSGD fill; LinearSGD markout;
    Ewma calibration; Ewma realized_ev; RunningMoments residuals;
    uint64_t observations{0}, fills{0};
    ActionModel(double lr=.003,double l2=.0001,double half_life=600.0):fill(lr,l2),markout(lr,l2),calibration(half_life),realized_ev(half_life){}
};

class ModelBank {
public:
    explicit ModelBank(const Config& cfg);
    struct Prediction { double pfill{0}, conditional{0}, base_ev{0}, calibrated_ev{0}, uncertainty{0}; };
    Prediction predict(CP cp,Side side,double offset,const FeatureState& state) const;
    void update(CP cp,Side side,double offset,const FeatureState& state,bool filled,double conditional_markout,double realized_ev);
    double side_rolling_ev(CP cp,Side side) const;
    uint64_t side_observations(CP cp,Side side) const;
    void save(const std::filesystem::path& path) const;
    void load(const std::filesystem::path& path);
    const std::vector<double>& offsets() const{return offsets_;}
private:
    size_t index(CP cp,Side side,double offset) const;
    std::vector<double> offsets_; std::vector<ActionModel> models_; double lr_,l2_,hl_;
};
} // namespace alosmm
