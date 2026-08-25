#include "alosmm/stats.hpp"
#include <boost/property_tree/json_parser.hpp>
#include <boost/property_tree/ptree.hpp>
namespace alosmm {
StatsCollector::StatsCollector(const Config&c):date_(utc_date()),cfg_(c){}
StatsCollector::~StatsCollector(){stop();}
void StatsCollector::open_files(){
    auto dir=std::filesystem::path(cfg_.stats_dir)/date_;std::filesystem::create_directories(dir);
    auto open=[&](std::ofstream&f,const std::string&n,const std::string&h){auto p=dir/n;bool fresh=!std::filesystem::exists(p)||std::filesystem::file_size(p)==0;f.open(p,std::ios::app);if(fresh)f<<h<<'\n';};
    open(decisions_,"shadow_decisions.csv","ts,token,strike,symbol,cp,reservation,bid_enabled,bid_price,bid_offset,bid_pfill,bid_ev,bid_reason,ask_enabled,ask_price,ask_offset,ask_pfill,ask_ev,ask_reason,ce_lots,pe_lots,reason");
    open(samples_,"feature_samples.csv","decision_ts,maturity_ts,token,strike,symbol,cp,side,offset,quote_price,pred_fill,pred_cond,pred_ev,filled,realized_cond,realized_ev,best_bid,best_ask,mid,spread,fair_value,surface_residual,micro_shift,dw5,ofi_z,synth_gap_z,intensity_z,quote_age_s,future_age_s,surface_age_s,tte_days,surface_rmse,pair_dispersion,surface_pairs,surface_forward,surface_theta,surface_rho,surface_phi,inventory,portfolio_delta,portfolio_vega,portfolio_gamma,option_delta,option_gamma,option_vega");
    open(fills_,"shadow_fills.csv","ts,shadow,token,strike,symbol,cp,side,price,quantity,order_id,ce_lots,pe_lots");
    open(health_,"health.csv","ts,feed_msgs,decisions,dropped,max_feed_lag_ms,max_queue_delay_us,max_surface_fit_us,max_decision_cycle_us,surface_ok_rate");
}
void StatsCollector::start(){if(running_.exchange(true))return;open_files();th_=std::thread([this]{run();});}
void StatsCollector::stop(){if(!running_.exchange(false))return;if(th_.joinable())th_.join();if(decisions_)decisions_.flush();if(samples_)samples_.flush();if(fills_)fills_.flush();if(health_)health_.flush();}
void StatsCollector::push(Rec&&r){if(!q_.push(r))++dropped_;}
void StatsCollector::run(){Rec r;while(running_||!q_.empty()){bool any=false;while(q_.pop(r)){any=true;switch(r.k){case K::Decision:decisions_<<r.line<<'\n';break;case K::Sample:samples_<<r.line<<'\n';break;case K::Fill:fills_<<r.line<<'\n';break;case K::Health:health_<<r.line<<'\n';break;}}if(any){decisions_.flush();samples_.flush();fills_.flush();health_.flush();}else std::this_thread::sleep_for(Ms(20));}}
static std::string csv_text(std::string s){for(char&c:s)if(c==',')c=';';return s;}
static std::string qstr(const QuoteAction&a){std::ostringstream o;o<<(a.enabled?1:0)<<','<<(a.enabled?a.price:0)<<','<<a.offset<<','<<a.predicted_fill<<','<<a.predicted_ev<<','<<csv_text(a.reason);return o.str();}
void StatsCollector::decision(const FeatureState&s,const ContractDecision&d,const InventoryBook&i,const Instrument&inst){std::ostringstream o;o<<iso_utc(s.ts_ns)<<','<<inst.token<<','<<inst.strike<<','<<csv_text(inst.trading_symbol)<<','<<to_string(s.cp)<<','<<std::setprecision(10)<<d.reservation_value<<','<<qstr(d.bid)<<','<<qstr(d.ask)<<','<<i.lots(CP::Call)<<','<<i.lots(CP::Put)<<','<<csv_text(d.reason);push({K::Decision,o.str()});}
void StatsCollector::counterfactual(const CounterfactualLabel&l,const FeatureState&s,const Instrument&inst){
    std::ostringstream key;key<<to_string(l.cp)<<'|'<<to_string(l.side)<<'|'<<std::fixed<<std::setprecision(2)<<l.offset;
    {std::lock_guard g(agg_mu_);auto&a=agg_[key.str()];++a.n;if(l.filled){++a.fill;a.cond.add(l.realized_conditional_markout);}a.ev.add(l.realized_ev);}
    if(!cfg_.write_compact_samples)return;std::uniform_real_distribution<double>u(0,1);if(u(rng_)>cfg_.research_sample_rate)return;
    std::ostringstream o;o<<std::setprecision(10)
      <<l.decision_ts_ns<<','<<l.maturity_ts_ns<<','<<inst.token<<','<<inst.strike<<','<<csv_text(inst.trading_symbol)<<','<<to_string(l.cp)<<','<<to_string(l.side)<<','<<l.offset<<','<<l.quote_price<<','
      <<l.predicted_fill<<','<<l.predicted_conditional<<','<<l.predicted_ev<<','<<(l.filled?1:0)<<','<<l.realized_conditional_markout<<','<<l.realized_ev<<','
      <<s.best_bid<<','<<s.best_ask<<','<<s.mid<<','<<s.spread<<','<<s.fair_value<<','<<s.surface_residual<<','<<s.micro_shift<<','<<s.dw5_imbalance<<','
      <<s.futures_ofi_z<<','<<s.synthetic_gap_z<<','<<s.trade_intensity_z<<','<<s.quote_age_s<<','<<s.future_age_s<<','<<s.surface_age_s<<','<<s.tte_days<<','
      <<s.surface_rmse<<','<<s.pair_dispersion<<','<<s.surface_pairs<<','<<s.surface_forward<<','<<s.surface_theta<<','<<s.surface_rho<<','<<s.surface_phi<<','
      <<s.inventory_lots<<','<<s.portfolio_delta<<','<<s.portfolio_vega<<','<<s.portfolio_gamma<<','<<s.greeks.delta<<','<<s.greeks.gamma<<','<<s.greeks.vega;
    push({K::Sample,o.str()});
}
void StatsCollector::fill(const FillEvent&f,const InventoryBook&i,bool shadow){std::ostringstream o;o<<iso_utc(f.ts_ns)<<','<<(shadow?1:0)<<','<<f.token<<','<<f.strike<<','<<csv_text(f.symbol)<<','<<to_string(f.cp)<<','<<to_string(f.side)<<','<<f.price<<','<<f.quantity<<','<<csv_text(f.order_id)<<','<<i.lots(CP::Call)<<','<<i.lots(CP::Put);push({K::Fill,o.str()});}
void StatsCollector::health(int64_t ts,uint64_t fm,uint64_t de,uint64_t dr,double lag,double qdelay,double surf_us,double cycle_us,double sr){std::ostringstream o;o<<iso_utc(ts)<<','<<fm<<','<<de<<','<<(dr+dropped_.load())<<','<<lag<<','<<qdelay<<','<<surf_us<<','<<cycle_us<<','<<sr;push({K::Health,o.str()});}
void StatsCollector::write_day_summary(const ModelBank&m,const InventoryBook&i){namespace pt=boost::property_tree;pt::ptree root;root.put("strategy",cfg_.strategy_name);root.put("date",date_);root.put("generated_at",iso_utc(now_unix_ns()));root.put("ce_lots",i.lots(CP::Call));root.put("pe_lots",i.lots(CP::Put));for(CP cp:{CP::Call,CP::Put})for(Side s:{Side::Buy,Side::Sell}){std::string k="side."+to_string(cp)+"."+to_string(s);root.put(k+".rolling_ev",m.side_rolling_ev(cp,s));root.put(k+".observations",m.side_observations(cp,s));}pt::ptree arr;{std::lock_guard g(agg_mu_);for(auto&[k,a]:agg_){pt::ptree x;x.put("key",k);x.put("n",a.n);x.put("fills",a.fill);x.put("fill_rate",a.n?static_cast<double>(a.fill)/a.n:0);x.put("mean_conditional_markout",a.cond.mean());x.put("mean_ev",a.ev.mean());x.put("sd_ev",a.ev.stdev());arr.push_back({"",x});}}root.add_child("action_stats",arr);auto dir=std::filesystem::path(cfg_.stats_dir)/date_;std::filesystem::create_directories(dir);pt::write_json((dir/"day_summary.json").string(),root);std::ofstream csv(dir/"action_stats.csv");csv<<"key,n,fills,fill_rate,mean_conditional_markout,mean_ev,sd_ev\n";std::lock_guard g(agg_mu_);for(auto&[k,a]:agg_)csv<<k<<','<<a.n<<','<<a.fill<<','<<(a.n?static_cast<double>(a.fill)/a.n:0)<<','<<a.cond.mean()<<','<<a.ev.mean()<<','<<a.ev.stdev()<<'\n';}
} // namespace alosmm
