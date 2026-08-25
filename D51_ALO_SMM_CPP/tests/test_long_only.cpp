#include "alosmm/policy.hpp"
#include <cassert>
int main(){
    alosmm::Config c;alosmm::ModelBank m(c);alosmm::AdaptivePolicy p(c,m);
    auto exp=alosmm::now_unix_ns()+1'000'000'000LL;
    alosmm::Instrument a{1,"nse_fo","A",alosmm::CP::Put,100,exp,65,.05};
    alosmm::Instrument b{2,"nse_fo","B",alosmm::CP::Put,150,exp,65,.05};
    bool blocked=false;try{p.on_fill(a,alosmm::Side::Sell,5,65);}catch(...){blocked=true;}assert(blocked);
    p.on_fill(a,alosmm::Side::Buy,5,65);assert(p.inventory().get(a).lots==1);assert(p.inventory().lots(alosmm::CP::Put)==1);
    blocked=false;try{p.on_fill(b,alosmm::Side::Sell,5.5,65);}catch(...){blocked=true;}assert(blocked); // owning A must never authorize selling B
    assert(p.inventory().get(a).lots==1);assert(p.inventory().get(b).lots==0);
    p.on_fill(a,alosmm::Side::Sell,5.5,65);assert(p.inventory().get(a).lots==0);assert(p.inventory().lots(alosmm::CP::Put)==0);
    return 0;
}
