#pragma once
#include "common.hpp"

namespace alosmm {
enum class CP : uint8_t { Call=0, Put=1 };
enum class Side : uint8_t { Buy=0, Sell=1 };
enum class Mode : uint8_t { Shadow=0, Live=1, Replay=2 };
enum class OrderState : uint8_t { None=0, Working=1, Filled=2, Cancelled=3, Rejected=4 };
inline std::string to_string(CP x){ return x==CP::Call?"CE":"PE"; }
inline std::string to_string(Side x){ return x==Side::Buy?"B":"S"; }
inline std::string to_string(Mode x){ return x==Mode::Shadow?"shadow":x==Mode::Live?"live":"replay"; }

struct DepthLevel { double price{0}; int64_t qty{0}; int32_t orders{0}; };
struct Book {
    uint32_t token{0}; std::string symbol; int64_t exchange_ts_ns{0}; int64_t recv_ts_ns{0};
    double ltp{0}; int64_t volume{0}; int64_t last_trade_qty{0}; int64_t oi{0};
    std::array<DepthLevel,5> bids{}; std::array<DepthLevel,5> asks{};
    int bid_count{0}; int ask_count{0};
    [[nodiscard]] double bid() const { return bid_count>0?bids[0].price:0.0; }
    [[nodiscard]] double ask() const { return ask_count>0?asks[0].price:0.0; }
    [[nodiscard]] double mid() const { return bid()>0&&ask()>0?0.5*(bid()+ask()):0.0; }
    [[nodiscard]] double spread() const { return ask()>0&&bid()>0?ask()-bid():0.0; }
    [[nodiscard]] bool valid() const { return bid()>0&&ask()>bid(); }
};

struct Instrument {
    uint32_t token{0}; std::string exchange_segment{"nse_fo"}; std::string trading_symbol;
    CP cp{CP::Call}; double strike{0}; int64_t expiry_unix_ns{0}; int lot_size{65}; double tick_size{0.05};
};

struct Greeks { double delta{0}, gamma{0}, vega{0}, theta_day{0}; };
struct SurfaceFit {
    bool valid{false}; double forward{0}; double theta{0}, rho{0}, phi{0};
    double rmse_iv{0}; int pairs{0}; double pair_dispersion{0}; int64_t fitted_at_ns{0};
};

struct FeatureState {
    int64_t ts_ns{0}; CP cp{CP::Call};
    double best_bid{0}, best_ask{0}, mid{0}, spread{0};
    double fair_value{0}; double surface_residual{0}; double micro_shift{0};
    double dw5_imbalance{0}; double futures_ofi_z{0}; double synthetic_gap_z{0};
    double trade_intensity_z{0}; double quote_age_s{0}; double future_age_s{0}; double surface_age_s{0};
    double tte_days{0}; double surface_rmse{0}; double pair_dispersion{0}; int surface_pairs{0};
    double surface_forward{0}, surface_theta{0}, surface_rho{0}, surface_phi{0};
    double inventory_lots{0}; double portfolio_delta{0}; double portfolio_vega{0}; double portfolio_gamma{0};
    Greeks greeks{};
};

struct QuoteAction {
    CP cp{CP::Call}; Side side{Side::Buy}; double offset{0}; double price{0};
    double predicted_fill{0}; double predicted_conditional_markout{0}; double predicted_ev{0};
    std::string reason{"off"}; bool enabled{false}; int64_t ts_ns{0};
};

struct OrderIntent {
    CP cp{CP::Call}; Side side{Side::Buy}; std::string symbol; uint32_t token{0}; int quantity{0};
    double price{0}; std::string product{"NRML"}; std::string validity{"DAY"}; std::string tag{"ALO_SMM"};
    std::string existing_order_id; enum class Kind:uint8_t{Place,Modify,Cancel} kind{Kind::Place}; int64_t ts_ns{0};
};

struct FillEvent { CP cp{CP::Call}; Side side{Side::Buy}; uint32_t token{0}; double strike{0}; std::string symbol; double price{0}; int quantity{0}; std::string order_id; int64_t ts_ns{0}; };
struct OrderUpdate {
    std::string order_id; std::string status; std::string symbol; uint32_t token{0}; Side side{Side::Buy};
    double avg_price{0}; int total_qty{0}; int filled_qty{0}; int remaining_qty{0}; int64_t recv_ts_ns{0};
};

struct InventoryPosition { int lots{0}; double avg_all_in_price{0}; };

struct CounterfactualLabel {
    int64_t decision_ts_ns{0}; int64_t maturity_ts_ns{0}; CP cp{CP::Call}; Side side{Side::Buy}; double offset{0};
    double quote_price{0}; double predicted_fill{0}; double predicted_conditional{0}; double predicted_ev{0};
    bool filled{false}; double realized_conditional_markout{0}; double realized_ev{0};
};
} // namespace alosmm
