#pragma once
#include "order_router.hpp"
#include "sfeed_client.hpp"
#include "stats.hpp"
namespace alosmm {
class Engine {
public:
    explicit Engine(Config cfg); int run(); int self_test();
private:
    struct Candidate {Side side;double offset,price;ModelBank::Prediction pred;};
    struct Pending {
        bool active{false};int64_t start_ns{0};int64_t maturity_ns{0};FeatureState state;Instrument inst;ContractDecision selected;double fut_entry{0};double delta{0};
        double min_ask{1e100},min_ltp{1e100},max_bid{-1e100},max_ltp{-1e100};std::vector<Candidate> candidates;
    };
    void on_book(const Book& b); void process_books(); void process_order_updates(); void update_signals(const Book& b,const std::optional<Book>& old);
    void decision_cycle(int64_t now); std::optional<std::pair<Instrument,Instrument>> select_atm(double ref) const;
    FeatureState build_state(const Instrument& inst,const Book& b,const SurfaceFit& fit,const std::array<Greeks,2>& gs,int64_t now);
    void mature(Pending& p,int64_t now); bool cf_fill(const Pending&p,Side side,double quote)const;
    double dw5(const Book&b)const; double micro_shift(const Book&b)const; void submit_live(const Instrument&i,const ContractDecision&d);
    Config cfg_;ModelBank models_;AdaptivePolicy policy_;SurfaceEngine surface_;StatutoryCostModel costs_;StatsCollector stats_;
    std::unordered_map<uint32_t,Book> books_;SpscRing<Book,32768> market_q_;SpscRing<OrderUpdate,2048> order_q_;std::atomic<bool>stop_{false};std::unique_ptr<SFeedClient> feed_;std::unique_ptr<OrderUpdateClient> order_updates_;std::unique_ptr<OrderRouter> router_;std::thread feed_thread_,order_update_thread_;
    struct LiveFillState{int filled_qty{0};double avg_price{0};};std::unordered_map<std::string,LiveFillState> live_fill_state_;
    std::array<Pending,2> pending_{};std::optional<Book> last_future_;double ofi_accum_{0},vol_accum_{0};RunningMoments ofi_hist_,vol_hist_,gap_hist_;Ewma basis_{1200};
    uint64_t feed_msgs_{0},decisions_{0},dropped_{0},surface_tries_{0},surface_ok_{0};
    double max_feed_lag_ms_{0},max_queue_delay_us_{0},max_surface_fit_us_{0},max_decision_cycle_us_{0};
    int64_t last_decision_ns_{0},last_health_ns_{0};std::optional<double> pinned_strike_;
};
} // namespace alosmm
