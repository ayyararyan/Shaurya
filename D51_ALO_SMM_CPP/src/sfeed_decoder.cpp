#include "alosmm/sfeed_decoder.hpp"
#include <cstring>
namespace alosmm {
template<class T> static T rd(const uint8_t* p){T v{};std::memcpy(&v,p,sizeof(T));return v;}
static int64_t feed_time_to_ns(int64_t x){if(x<=0)return 0;if(x>10'000'000'000'000LL)return x*1'000LL;if(x>10'000'000'000LL)return x*1'000'000LL;return x*1'000'000'000LL;}
std::vector<Book> SFeedDecoder::decode_binary(std::span<const uint8_t> f,int64_t recv)const{
    std::vector<Book> out;size_t off=0;while(off+9<=f.size()){
        const auto*p=f.data()+off;uint16_t len=rd<uint16_t>(p),code=rd<uint16_t>(p+2);if(len<9||off+len>f.size())break;int8_t ex=rd<int8_t>(p+4);uint8_t level=rd<uint8_t>(p+5);(void)level;
        if(code==7208 && len>=144){const uint8_t*b=p+9;Book q;q.recv_ts_ns=recv;q.token=rd<uint32_t>(b+0);q.volume=rd<int64_t>(b+20);q.exchange_ts_ns=feed_time_to_ns(rd<int64_t>(b+36));q.ltp=static_cast<double>(rd<uint32_t>(b+60))/divider(ex);q.last_trade_qty=rd<int64_t>(b+64);q.oi=rd<uint32_t>(b+94);uint32_t nb=rd<uint32_t>(b+80),na=rd<uint32_t>(b+84);size_t dpos=off+144;auto read_side=[&](std::array<DepthLevel,5>&dst,uint32_t n,int&cnt){cnt=0;for(uint32_t i=0;i<n&&dpos+16<=off+len;++i){int64_t qty=rd<int64_t>(f.data()+dpos);int32_t pr=rd<int32_t>(f.data()+dpos+8),ord=rd<int32_t>(f.data()+dpos+12);if(i<5){dst[i]={static_cast<double>(pr)/divider(ex),qty,ord};++cnt;}dpos+=16;}};read_side(q.bids,nb,q.bid_count);read_side(q.asks,na,q.ask_count);out.push_back(q);}
        off+=len;
    }return out;
}
} // namespace alosmm
