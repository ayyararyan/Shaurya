#include "alosmm/online_model.hpp"
namespace alosmm {
FeatureVector make_features(const FeatureState& s,double offset,Side side){
    FeatureVector f; const double sign=side==Side::Buy?1.0:-1.0;
    f.x={1.0, offset, s.surface_residual, s.micro_shift, s.dw5_imbalance,
         s.futures_ofi_z, s.synthetic_gap_z, s.trade_intensity_z, s.spread,
         std::log1p(std::max(0.0,s.quote_age_s)), std::log1p(std::max(0.0,s.future_age_s)),
         std::log1p(std::max(0.0,s.surface_age_s)), s.surface_rmse, s.pair_dispersion,
         s.inventory_lots, s.portfolio_delta, s.portfolio_vega*1e-3, s.portfolio_gamma*1e3,
         s.greeks.delta*sign, std::log1p(std::max(0.0,s.tte_days))};
    for(auto& x:f.x){if(!finite(x))x=0.0;}
    return f;
}
FeatureVector OnlineStandardizer::transform_and_update(const FeatureVector& raw,bool update){
    FeatureVector z;
    for(size_t i=0;i<kFeatureCount;++i){
        const double x=clamp(raw.x[i],-1e6,1e6);
        if(update){ ++n_[i]; const double d=x-mean_[i]; mean_[i]+=d/static_cast<double>(n_[i]); m2_[i]+=d*(x-mean_[i]); }
        const double sd=n_[i]>20?std::sqrt(std::max(1e-8,m2_[i]/static_cast<double>(n_[i]-1))):1.0;
        z.x[i]=clamp((x-mean_[i])/sd,-8.0,8.0);
    }
    z.x[0]=1.0; return z;
}
void OnlineStandardizer::save(std::ostream& os)const{ for(size_t i=0;i<kFeatureCount;++i)os<<n_[i]<<' '<<std::setprecision(17)<<mean_[i]<<' '<<m2_[i]<<'\n'; }
void OnlineStandardizer::load(std::istream& is){ for(size_t i=0;i<kFeatureCount;++i)is>>n_[i]>>mean_[i]>>m2_[i]; }

double LogisticSGD::predict(const FeatureVector& x)const{ double z=b_; for(size_t i=0;i<kFeatureCount;++i)z+=w_[i]*x.x[i]; z=clamp(z,-30,30); return 1.0/(1.0+std::exp(-z)); }
void LogisticSGD::update(const FeatureVector& x,double y){ const double p=predict(x),g=clamp(p-y,-1.0,1.0); b_-=lr_*g; for(size_t i=0;i<kFeatureCount;++i)w_[i]-=lr_*(g*x.x[i]+l2_*w_[i]); }
void LogisticSGD::save(std::ostream& os)const{os<<std::setprecision(17)<<b_<<' '<<lr_<<' '<<l2_<<'\n';for(double x:w_)os<<x<<' ';os<<'\n';}
void LogisticSGD::load(std::istream& is){is>>b_>>lr_>>l2_;for(double& x:w_)is>>x;}

double LinearSGD::predict(const FeatureVector& x)const{double z=b_;for(size_t i=0;i<kFeatureCount;++i)z+=w_[i]*x.x[i];return clamp(z,-5.0,5.0);}
void LinearSGD::update(const FeatureVector& x,double y,double weight){ const double pred=predict(x),e=clamp((pred-y)*weight,-5.0,5.0); b_-=lr_*e;for(size_t i=0;i<kFeatureCount;++i)w_[i]-=lr_*(e*x.x[i]+l2_*w_[i]);}
void LinearSGD::save(std::ostream& os)const{os<<std::setprecision(17)<<b_<<' '<<lr_<<' '<<l2_<<'\n';for(double x:w_)os<<x<<' ';os<<'\n';}
void LinearSGD::load(std::istream& is){is>>b_>>lr_>>l2_;for(double& x:w_)is>>x;}

ModelBank::ModelBank(const Config& c):offsets_(c.offsets),lr_(c.model_learning_rate),l2_(c.model_l2),hl_(c.calibration_half_life){
    models_.reserve(4*offsets_.size()); for(size_t i=0;i<4*offsets_.size();++i)models_.emplace_back(lr_,l2_,hl_);
}
size_t ModelBank::index(CP cp,Side side,double off)const{ size_t oi=0; double best=1e9; for(size_t i=0;i<offsets_.size();++i){double d=std::abs(offsets_[i]-off);if(d<best){best=d;oi=i;}} return (static_cast<size_t>(cp)*2+static_cast<size_t>(side))*offsets_.size()+oi; }
ModelBank::Prediction ModelBank::predict(CP cp,Side side,double off,const FeatureState& s)const{
    const auto& m=models_[index(cp,side,off)]; auto raw=make_features(s,off,side); auto sc=const_cast<OnlineStandardizer&>(m.scale).transform_and_update(raw,false);
    Prediction p; p.pfill=m.fill.predict(sc); p.conditional=m.markout.predict(sc); p.base_ev=p.pfill*p.conditional; p.calibrated_ev=p.base_ev+m.calibration.value(); p.uncertainty=(m.residuals.n()>30?m.residuals.stdev()/std::sqrt(static_cast<double>(m.residuals.n())):0.05); return p;
}
void ModelBank::update(CP cp,Side side,double off,const FeatureState& s,bool filled,double conditional,double realized){
    auto& m=models_[index(cp,side,off)]; auto raw=make_features(s,off,side); auto sc=m.scale.transform_and_update(raw,true); const double old_p=m.fill.predict(sc),old_m=m.markout.predict(sc),pred=old_p*old_m;
    m.fill.update(sc,filled?1.0:0.0); if(filled){m.markout.update(sc,conditional);m.residuals.add(conditional-old_m);++m.fills;} m.calibration.update(realized-pred);m.realized_ev.update(realized);++m.observations;
}
double ModelBank::side_rolling_ev(CP cp,Side side)const{ double num=0,den=0;for(double o:offsets_){const auto&m=models_[index(cp,side,o)];if(m.realized_ev.count()){const double w=std::sqrt(static_cast<double>(m.realized_ev.count()));num+=w*m.realized_ev.value();den+=w;}}return den?num/den:0;}
uint64_t ModelBank::side_observations(CP cp,Side side)const{uint64_t n=0;for(double o:offsets_)n+=models_[index(cp,side,o)].observations;return n;}
void ModelBank::save(const std::filesystem::path& p)const{std::filesystem::create_directories(p.parent_path());std::ofstream os(p,std::ios::binary);os<<"ALO_MODEL_V1 "<<offsets_.size()<<'\n';for(double o:offsets_)os<<std::setprecision(17)<<o<<' ';os<<'\n';for(const auto&m:models_){os<<m.observations<<' '<<m.fills<<' '<<m.calibration.value()<<' '<<m.calibration.count()<<' '<<m.realized_ev.value()<<' '<<m.realized_ev.count()<<'\n';m.scale.save(os);m.fill.save(os);m.markout.save(os);} }
void ModelBank::load(const std::filesystem::path& p){ if(!std::filesystem::exists(p))return;std::ifstream is(p,std::ios::binary);std::string magic;size_t n;is>>magic>>n;if(magic!="ALO_MODEL_V1"||n!=offsets_.size())throw std::runtime_error("model state mismatch");double x;for(size_t i=0;i<n;++i){is>>x;if(std::abs(x-offsets_[i])>1e-8)throw std::runtime_error("model offset mismatch");}for(auto&m:models_){uint64_t ob,fi,cn,en;double cv,ev;is>>ob>>fi>>cv>>cn>>ev>>en;m.observations=ob;m.fills=fi;m.calibration.restore(cv,cn);m.realized_ev.restore(ev,en);m.scale.load(is);m.fill.load(is);m.markout.load(is);} }
} // namespace alosmm
