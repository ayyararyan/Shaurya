#include "alosmm/policy.hpp"
#include <cassert>
int main(){alosmm::Config c;c.min_buy_ev=-1;c.min_sell_ev=-1;c.require_surface=false;alosmm::ModelBank m(c);alosmm::AdaptivePolicy p(c,m);alosmm::FeatureState s;s.ts_ns=alosmm::now_unix_ns();s.cp=alosmm::CP::Call;s.best_bid=10;s.best_ask=10.15;s.mid=10.075;s.spread=.15;s.fair_value=10.1;s.surface_pairs=10;s.greeks.delta=.5;alosmm::Instrument i{1,"nse_fo","X",alosmm::CP::Call,100,s.ts_ns+1000000000LL,65,.05};std::array<alosmm::Greeks,2>g{};auto d=p.decide(s,i,g);assert(!d.ask.enabled);return 0;}
