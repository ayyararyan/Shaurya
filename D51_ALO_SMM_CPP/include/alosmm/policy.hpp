#pragma once
#include "online_model.hpp"
#include "surface.hpp"
namespace alosmm {
class StatutoryCostModel {
public:
    explicit StatutoryCostModel(const Config& c):brokerage_(c.brokerage_per_order_rupees),stt_(c.stt_sell),ex_(c.exchange_premium_turnover),sebi_(c.sebi_turnover),stamp_(c.stamp_buy),gst_(c.gst){}
    double buy_points(double premium,int qty) const;
    double sell_points(double premium,int qty) const;
private: double brokerage_,stt_,ex_,sebi_,stamp_,gst_;
};

class InventoryBook {
public:
    explicit InventoryBook(int cap):cap_(cap){}
    bool can_buy(const Instrument& inst)const{return get(inst).lots<cap_;}
    bool can_sell(const Instrument& inst)const{return get(inst).lots>0;}
    const InventoryPosition& get(const Instrument& inst)const;
    int lots(CP cp)const;
    int total_lots()const{return lots(CP::Call)+lots(CP::Put);}
    bool empty()const{return total_lots()==0;}
    double avg_all_in(const Instrument& inst)const{return get(inst).avg_all_in_price;}
    void on_fill(const Instrument& inst,Side side,double price,int lots,double all_in_per_unit);
    // Portfolio Greeks use the current pinned ATM pair. The engine pins the strike while inventory exists.
    double delta(const std::array<Greeks,2>& g)const;
    double vega(const std::array<Greeks,2>& g)const;
    double gamma(const std::array<Greeks,2>& g)const;
private:
    int cap_;
    std::unordered_map<uint32_t,InventoryPosition> pos_;
    std::unordered_map<uint32_t,CP> cp_by_token_;
    static const InventoryPosition& zero_position();
};

struct ContractDecision { QuoteAction bid; QuoteAction ask; double reservation_value{0}; bool eligible{false}; std::string reason; };

class AdaptivePolicy {
public:
    AdaptivePolicy(const Config& cfg,ModelBank& models);
    ContractDecision decide(const FeatureState& s,const Instrument& inst,const std::array<Greeks,2>& portfolio_greeks);
    void on_fill(const Instrument& inst,Side side,double price,int quantity);
    InventoryBook& inventory(){return inventory_;} const InventoryBook& inventory()const{return inventory_;}
    bool should_replace(const Instrument& inst,const ContractDecision& d);
private:
    double inventory_risk_delta(CP cp,Side side,double pfill,const std::array<Greeks,2>& g) const;
    bool eligible(const FeatureState& s,std::string& why)const;
    struct LastQuote { uint32_t token{0}; std::optional<double> bid; std::optional<double> ask; };
    const Config& cfg_; ModelBank& models_; StatutoryCostModel costs_; InventoryBook inventory_;
    std::array<LastQuote,2> last_quotes_{};
};
} // namespace alosmm
