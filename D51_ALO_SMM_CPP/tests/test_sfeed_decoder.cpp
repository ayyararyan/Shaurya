#include "alosmm/sfeed_decoder.hpp"
#include <cassert>
#include <cstring>
using namespace alosmm;
template<class T>static void put(std::vector<uint8_t>&b,size_t o,T v){std::memcpy(b.data()+o,&v,sizeof(v));}
static std::vector<uint8_t> packet(uint32_t token,int32_t bid_px,int32_t ask_px){
    // Header 9 + fixed market-picture body through byte 143 + two 16-byte depth rows.
    std::vector<uint8_t>b(176,0);put<uint16_t>(b,0,176);put<uint16_t>(b,2,7208);put<int8_t>(b,4,1);put<uint8_t>(b,5,2);
    put<uint32_t>(b,9,token);put<int64_t>(b,29,1000);put<int64_t>(b,45,1700000000);put<uint32_t>(b,69,10000);put<uint32_t>(b,89,1);put<uint32_t>(b,93,1);
    put<int64_t>(b,144,11);put<int32_t>(b,152,bid_px);put<int32_t>(b,156,3);
    put<int64_t>(b,160,13);put<int32_t>(b,168,ask_px);put<int32_t>(b,172,4);
    return b;
}
int main(){
    SFeedDecoder d;d.set_price_divider(1,100.0);
    auto a=packet(123,9995,10005);auto out=d.decode_binary(a,42);assert(out.size()==1);assert(out[0].token==123);assert(out[0].bid_count==1&&out[0].ask_count==1);assert(std::abs(out[0].bid()-99.95)<1e-9);assert(std::abs(out[0].ask()-100.05)<1e-9);
    // Regression: depth rows in the second packet of a native_batch frame must be packet-relative.
    auto b=packet(456,19995,20005);std::vector<uint8_t> batch;batch.reserve(a.size()+b.size());batch.insert(batch.end(),a.begin(),a.end());batch.insert(batch.end(),b.begin(),b.end());
    auto both=d.decode_binary(batch,43);assert(both.size()==2);assert(both[0].token==123&&both[1].token==456);assert(std::abs(both[1].bid()-199.95)<1e-9);assert(std::abs(both[1].ask()-200.05)<1e-9);
    return 0;
}
