#include "alosmm/surface.hpp"
namespace alosmm {
static double norm_cdf(double x){return 0.5*std::erfc(-x/std::sqrt(2.0));}
static double norm_pdf(double x){constexpr double inv=0.3989422804014327;return inv*std::exp(-0.5*x*x);}
double SurfaceEngine::black_price(double F,double K,double T,double v,bool call,double r){ if(T<=0||v<=0){return std::exp(-r*std::max(0.0,T))*std::max(call?F-K:K-F,0.0);} const double s=v*std::sqrt(T),d1=(std::log(F/K)+0.5*s*s)/s,d2=d1-s,df=std::exp(-r*T);return call?df*(F*norm_cdf(d1)-K*norm_cdf(d2)):df*(K*norm_cdf(-d2)-F*norm_cdf(-d1));}
double SurfaceEngine::implied_vol(double price,double F,double K,double T,bool call,double r){ if(price<=0||F<=0||K<=0||T<=1e-8)return std::numeric_limits<double>::quiet_NaN(); double lo=.01,hi=5.0; if(black_price(F,K,T,hi,call,r)<price)return hi; for(int i=0;i<70;++i){double m=.5*(lo+hi);if(black_price(F,K,T,m,call,r)>price)hi=m;else lo=m;}return .5*(lo+hi);}
double SurfaceEngine::ssvi_total_variance(double k,double th,double rho,double phi){const double a=phi*k+rho;return 0.5*th*(1.0+rho*phi*k+std::sqrt(a*a+1-rho*rho));}

SurfaceFit SurfaceEngine::fit_leave_strike_out(const std::vector<Instrument>& ins,const std::unordered_map<uint32_t,Book>& books,double exclude,int64_t now){
    struct Pair{double K=0,c=0,p=0;bool hc=false,hp=false;}; std::map<double,Pair> pm;
    int64_t expiry=0; for(const auto&i:ins){ if(expiry==0)expiry=i.expiry_unix_ns; if(i.expiry_unix_ns!=expiry)continue;auto it=books.find(i.token);if(it==books.end()||!it->second.valid())continue;const auto&b=it->second;if(ns_to_seconds(now-b.recv_ts_ns)>2.0)continue;auto&x=pm[i.strike];x.K=i.strike;if(i.cp==CP::Call){x.c=b.mid();x.hc=true;}else{x.p=b.mid();x.hp=true;} }
    const double T=std::max(1e-8,ns_to_seconds(expiry-now)/(365.0*24*3600)); std::vector<double> fwds; for(auto&[K,x]:pm)if(x.hc&&x.hp&&std::abs(K-exclude)>1e-9)fwds.push_back(K+std::exp(rate_*T)*(x.c-x.p));
    SurfaceFit out;out.fitted_at_ns=now;out.pairs=static_cast<int>(fwds.size());if(fwds.size()<3)return out;std::sort(fwds.begin(),fwds.end());out.forward=fwds[fwds.size()/2];std::vector<double> dev;for(double f:fwds)dev.push_back(std::abs(f-out.forward));std::sort(dev.begin(),dev.end());out.pair_dispersion=dev[dev.size()/2];
    struct Pt{double k,w;};std::vector<Pt> pts;for(auto&[K,x]:pm){if(std::abs(K-exclude)<1e-9)continue;double pr=0;bool call=K>=out.forward;if(call&&x.hc)pr=x.c;else if(!call&&x.hp)pr=x.p;else if(x.hc){pr=x.c;call=true;}else if(x.hp){pr=x.p;call=false;}else continue;double iv=implied_vol(pr,out.forward,K,T,call,rate_);if(!finite(iv)||iv<.01||iv>3)continue;pts.push_back({std::log(K/out.forward),iv*iv*T});}
    if(pts.size()<5)return out;
    double th=prev_&&prev_->valid?prev_->theta:0,rho=prev_&&prev_->valid?prev_->rho:-0.2,phi=prev_&&prev_->valid?prev_->phi:1.0;
    if(th<=0){std::vector<double>w;for(auto&p:pts)w.push_back(p.w);std::sort(w.begin(),w.end());th=w[w.size()/2];}
    th=clamp(th,1e-8,1.0);rho=clamp(rho,-.95,.95);phi=clamp(phi,.01,20.0);
    auto loss=[&](double a,double b,double c){double z=0;for(auto&p:pts){double e=ssvi_total_variance(p.k,a,b,c)-p.w;double ae=std::abs(e),delta=0.0002;z+=ae<=delta?.5*e*e:delta*(ae-.5*delta);}return z/pts.size();};
    double best=loss(th,rho,phi);double st=.35,sr=.25,sp=.45;
    for(int iter=0;iter<12;++iter){bool improved=false;for(int dim=0;dim<3;++dim){for(int sg:{-1,1}){double a=th,b=rho,c=phi;if(dim==0)a=clamp(th*(1+sg*st),1e-8,1.0);if(dim==1)b=clamp(rho+sg*sr,-.98,.98);if(dim==2)c=clamp(phi*(1+sg*sp),.005,30.0);double q=loss(a,b,c);if(q<best){th=a;rho=b;phi=c;best=q;improved=true;}}}if(!improved){st*=.55;sr*=.55;sp*=.55;}}
    // Conservative no-butterfly sufficient-style caps for a slice.
    phi=std::min(phi,4.0/(th*(1.0+std::abs(rho))+1e-12));
    double sq=0;int n=0;for(auto&p:pts){double fitw=ssvi_total_variance(p.k,th,rho,phi);if(fitw<=0)continue;double ivf=std::sqrt(fitw/T),iv=std::sqrt(p.w/T);sq+=(ivf-iv)*(ivf-iv);++n;}
    out.theta=th;out.rho=rho;out.phi=phi;out.rmse_iv=n?std::sqrt(sq/n):999;out.valid=n>=5&&out.forward>0&&finite(out.rmse_iv);if(out.valid)prev_=out;return out;
}
double SurfaceEngine::fair_option_price(const Instrument&i,const SurfaceFit&f,int64_t now)const{if(!f.valid)return 0;double T=std::max(1e-8,ns_to_seconds(i.expiry_unix_ns-now)/(365.0*24*3600)),k=std::log(i.strike/f.forward),w=ssvi_total_variance(k,f.theta,f.rho,f.phi),v=std::sqrt(std::max(w,1e-12)/T);return black_price(f.forward,i.strike,T,v,i.cp==CP::Call,rate_);}
Greeks SurfaceEngine::greeks(const Instrument&i,const SurfaceFit&f,int64_t now)const{Greeks g;if(!f.valid)return g;double T=std::max(1e-8,ns_to_seconds(i.expiry_unix_ns-now)/(365.0*24*3600)),k=std::log(i.strike/f.forward),w=ssvi_total_variance(k,f.theta,f.rho,f.phi),v=std::sqrt(std::max(w,1e-12)/T),s=v*std::sqrt(T),d1=(std::log(f.forward/i.strike)+.5*s*s)/s,df=std::exp(-rate_*T);g.delta=(i.cp==CP::Call?norm_cdf(d1):norm_cdf(d1)-1.0);g.gamma=df*norm_pdf(d1)/(f.forward*v*std::sqrt(T));g.vega=df*f.forward*norm_pdf(d1)*std::sqrt(T);double p=black_price(f.forward,i.strike,T,v,i.cp==CP::Call,rate_),dt=1.0/365.0,p2=black_price(f.forward,i.strike,std::max(1e-8,T-dt),v,i.cp==CP::Call,rate_);g.theta_day=p2-p;return g;}
} // namespace alosmm
