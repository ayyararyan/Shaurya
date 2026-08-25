#include "alosmm/config.hpp"
#include <boost/property_tree/json_parser.hpp>
#include <boost/property_tree/ptree.hpp>

namespace alosmm {
namespace pt=boost::property_tree;
static Mode parse_mode(const std::string& x){ if(x=="live") return Mode::Live; if(x=="replay") return Mode::Replay; return Mode::Shadow; }
static CP parse_cp(const std::string& x){ return (x=="PE"||x=="P"||x=="put")?CP::Put:CP::Call; }

template<class T> static void maybe_get(const pt::ptree& p,const char* k,T& out){ if(auto v=p.get_optional<T>(k)) out=*v; }

Config load_config(const std::filesystem::path& path){
    Config c; pt::ptree p; pt::read_json(path.string(),p);
    c.mode=parse_mode(p.get<std::string>("mode","shadow"));
#define MGET(k,f) maybe_get(p,k,c.f)
    MGET("strategy_name",strategy_name); MGET("market_feed_url",market_feed_url); MGET("login_url",login_url); MGET("validate_url",validate_url);
    MGET("paths.state_dir",state_dir); MGET("paths.stats_dir",stats_dir); MGET("paths.log_dir",log_dir); MGET("paths.instruments_csv",instruments_csv);
    MGET("credentials.consumer_key_env",consumer_key_env); MGET("credentials.mobile_env",mobile_env); MGET("credentials.ucc_env",ucc_env);
    MGET("credentials.totp_env",totp_env); MGET("credentials.totp_secret_env",totp_secret_env); MGET("credentials.mpin_env",mpin_env); MGET("safety.live_ack_env",live_ack_env); MGET("safety.live_ack_phrase",live_ack_phrase); MGET("safety.live_flat_ack_env",live_flat_ack_env); MGET("safety.live_flat_ack_phrase",live_flat_ack_phrase);
    MGET("futures.token",futures_token); MGET("futures.symbol",futures_symbol); MGET("futures.lot_size",futures_lot_size);
    MGET("engine.decision_interval_ms",decision_interval_ms); MGET("engine.counterfactual_horizon_ms",counterfactual_horizon_ms); MGET("engine.health_interval_s",health_interval_s);
    MGET("engine.max_orders_per_second",max_orders_per_second); MGET("engine.max_lots_per_contract",max_lots_per_contract); MGET("engine.quantity_lots",quantity_lots);
    MGET("quality.min_surface_pairs",min_surface_pairs); MGET("quality.max_quote_age_s",max_quote_age_s); MGET("quality.max_future_age_s",max_future_age_s);
    MGET("quality.max_surface_age_s",max_surface_age_s); MGET("quality.max_surface_rmse_iv",max_surface_rmse_iv); MGET("quality.max_pair_dispersion",max_pair_dispersion);
    MGET("policy.tick_size",tick_size); MGET("policy.min_buy_ev",min_buy_ev); MGET("policy.min_sell_ev",min_sell_ev); MGET("policy.min_fill_probability",min_fill_probability);
    MGET("policy.inventory_penalty",inventory_penalty); MGET("policy.delta_penalty",delta_penalty); MGET("policy.vega_penalty",vega_penalty); MGET("policy.gamma_penalty",gamma_penalty);
    MGET("policy.churn_penalty",churn_penalty); MGET("policy.uncertainty_penalty",uncertainty_penalty); MGET("policy.side_kill_threshold",side_kill_threshold);
    MGET("policy.side_kill_half_life",side_kill_half_life); MGET("policy.update_threshold_points",update_threshold_points);
    MGET("learning.model_learning_rate",model_learning_rate); MGET("learning.model_l2",model_l2); MGET("learning.calibration_half_life",calibration_half_life);
    MGET("learning.research_sample_rate",research_sample_rate); MGET("learning.write_compact_samples",write_compact_samples);
    MGET("costs.brokerage_per_order_rupees",brokerage_per_order_rupees); MGET("costs.stt_sell",stt_sell); MGET("costs.exchange_premium_turnover",exchange_premium_turnover); MGET("costs.sebi_turnover",sebi_turnover); MGET("costs.stamp_buy",stamp_buy); MGET("costs.gst",gst);
    MGET("quality.require_surface",require_surface); MGET("engine.allow_hold_loss",allow_hold_loss); MGET("engine.dry_connect",dry_connect);
#undef MGET
    if(auto offs=p.get_child_optional("policy.offsets")){ c.offsets.clear(); for(const auto& kv:*offs)c.offsets.push_back(kv.second.get_value<double>()); }
    const auto base=path.parent_path(); std::filesystem::path ip=c.instruments_csv; if(ip.is_relative()) ip=base.parent_path()/ip;
    if(std::filesystem::exists(ip)) load_instruments_csv(c,ip);
    for(size_t i=0;i<c.instruments.size();++i){ if(c.instruments[i].cp==CP::Call && c.atm_call_index<0)c.atm_call_index=static_cast<int>(i); if(c.instruments[i].cp==CP::Put&&c.atm_put_index<0)c.atm_put_index=static_cast<int>(i); }
    return c;
}

static std::vector<std::string> split_csv(const std::string& s){ std::vector<std::string> v; std::string cur; bool quote=false; for(char ch:s){ if(ch=='\"')quote=!quote; else if(ch==','&&!quote){v.push_back(cur);cur.clear();}else cur+=ch;}v.push_back(cur);return v; }
void load_instruments_csv(Config& cfg,const std::filesystem::path& path){
    std::ifstream f(path); if(!f)throw std::runtime_error("cannot open instruments CSV: "+path.string());
    std::string line; std::getline(f,line); auto h=split_csv(line); std::unordered_map<std::string,size_t> ix; for(size_t i=0;i<h.size();++i)ix[h[i]]=i;
    auto get=[&](const std::vector<std::string>& r,const std::string& k)->std::string{ auto it=ix.find(k); return (it!=ix.end()&&it->second<r.size())?r[it->second]:"";};
    while(std::getline(f,line)){ if(line.empty()||line[0]=='#')continue; auto r=split_csv(line); Instrument z; z.token=static_cast<uint32_t>(std::stoul(get(r,"token"))); z.exchange_segment=get(r,"exchange_segment"); z.trading_symbol=get(r,"trading_symbol"); z.cp=parse_cp(get(r,"cp")); z.strike=std::stod(get(r,"strike")); z.expiry_unix_ns=std::stoll(get(r,"expiry_unix_ns")); if(!get(r,"lot_size").empty())z.lot_size=std::stoi(get(r,"lot_size")); if(!get(r,"tick_size").empty())z.tick_size=std::stod(get(r,"tick_size")); cfg.instruments.push_back(std::move(z)); }
}
std::string config_summary(const Config& c){ std::ostringstream o; o<<c.strategy_name<<" mode="<<to_string(c.mode)<<" instruments="<<c.instruments.size()<<" decision_ms="<<c.decision_interval_ms<<" horizon_ms="<<c.counterfactual_horizon_ms<<" max_ops="<<c.max_orders_per_second; return o.str(); }
} // namespace alosmm
