#pragma once
#include "types.hpp"
namespace alosmm {
struct Config {
    Mode mode{Mode::Shadow};
    std::string strategy_name{"D51 ALO-SMM"};
    std::string market_feed_url{"wss://sfeed.kotaksecurities.com/apifeed"};
    std::string login_url{"https://mis.kotaksecurities.com/login/1.0/tradeApiLogin"};
    std::string validate_url{"https://mis.kotaksecurities.com/login/1.0/tradeApiValidate"};
    std::string state_dir{"state"}; std::string stats_dir{"stats"}; std::string log_dir{"logs"};
    std::string instruments_csv{"config/instruments.csv"};
    std::string consumer_key_env{"KOTAK_CONSUMER_KEY"}; std::string mobile_env{"KOTAK_MOBILE"};
    std::string ucc_env{"KOTAK_UCC"}; std::string totp_env{"KOTAK_TOTP"}; std::string totp_secret_env{"KOTAK_TOTP_SECRET"}; std::string mpin_env{"KOTAK_MPIN"};
    std::string live_ack_env{"ALO_LIVE_ACK"}; std::string live_ack_phrase{"I_UNDERSTAND_LIVE_ORDERS"};
    std::string live_flat_ack_env{"ALO_LIVE_START_FLAT_ACK"}; std::string live_flat_ack_phrase{"I_CONFIRM_ACCOUNT_FLAT"};
    uint32_t futures_token{0}; std::string futures_symbol; int futures_lot_size{65};
    int atm_call_index{-1}; int atm_put_index{-1};
    int decision_interval_ms{1000}; int counterfactual_horizon_ms{1000}; int health_interval_s{60};
    int max_orders_per_second{8}; int max_lots_per_contract{2}; int quantity_lots{1};
    int min_surface_pairs{5}; double max_quote_age_s{1.5}; double max_future_age_s{1.5};
    double max_surface_age_s{2.0}; double max_surface_rmse_iv{0.06}; double max_pair_dispersion{3.0};
    double tick_size{0.05}; double min_buy_ev{0.00015}; double min_sell_ev{-0.00005};
    double min_fill_probability{0.001}; double inventory_penalty{0.00020}; double delta_penalty{0.00020};
    double vega_penalty{0.00001}; double gamma_penalty{0.00001}; double churn_penalty{0.00002};
    double uncertainty_penalty{0.00005}; double side_kill_threshold{-0.0010}; double side_kill_half_life{300.0};
    double model_learning_rate{0.003}; double model_l2{0.0001}; double calibration_half_life{600.0};
    double update_threshold_points{0.05}; double research_sample_rate{0.10};
    double brokerage_per_order_rupees{0.0}; double stt_sell{0.0015}; double exchange_premium_turnover{3553.0/1e7};
    double sebi_turnover{10.0/1e7}; double stamp_buy{0.00003}; double gst{0.18};
    bool require_surface{true}; bool allow_hold_loss{true}; bool write_compact_samples{true}; bool dry_connect{false};
    std::vector<double> offsets{0.05,0.10,0.15,0.20,0.30,0.40,0.50};
    std::vector<Instrument> instruments;
};
Config load_config(const std::filesystem::path& path);
void load_instruments_csv(Config& cfg, const std::filesystem::path& path);
std::string config_summary(const Config& cfg);
} // namespace alosmm
