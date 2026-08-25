#pragma once
#include "policy.hpp"
#include "spsc_ring.hpp"
namespace alosmm {
class StatsCollector {
public:
    explicit StatsCollector(const Config& cfg); ~StatsCollector();
    void start(); void stop();
    void decision(const FeatureState& s,const ContractDecision& d,const InventoryBook& inv,const Instrument& inst);
    void counterfactual(const CounterfactualLabel& l,const FeatureState& s,const Instrument& inst);
    void fill(const FillEvent& f,const InventoryBook& inv,bool shadow);
    void health(int64_t ts,uint64_t feed_msgs,uint64_t decisions,uint64_t dropped,double max_feed_lag_ms,double max_queue_delay_us,double max_surface_fit_us,double max_decision_cycle_us,double surface_ok_rate);
    void write_day_summary(const ModelBank& models,const InventoryBook& inv);
private:
    enum class K:uint8_t{Decision,Sample,Fill,Health}; struct Rec{K k;std::string line;};
    void run(); void open_files(); void push(Rec&& r); std::string date_;
    const Config& cfg_; std::atomic<bool> running_{false}; std::thread th_; SpscRing<Rec,16384> q_; std::atomic<uint64_t>dropped_{0};
    std::ofstream decisions_,samples_,fills_,health_;
    struct Agg{uint64_t n=0,fill=0;RunningMoments cond,ev;};std::map<std::string,Agg> agg_;std::mutex agg_mu_; std::mt19937_64 rng_{0xD51A1055};
};
} // namespace alosmm
