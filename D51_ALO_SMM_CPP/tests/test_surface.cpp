#include "alosmm/surface.hpp"
#include <cassert>
int main(){double p=alosmm::SurfaceEngine::black_price(100,100,30.0/365,.20,true,.06);assert(p>1&&p<5);double iv=alosmm::SurfaceEngine::implied_vol(p,100,100,30.0/365,true,.06);assert(std::abs(iv-.20)<1e-5);double w=alosmm::SurfaceEngine::ssvi_total_variance(0,.02,-.3,1.0);assert(w>0);return 0;}
