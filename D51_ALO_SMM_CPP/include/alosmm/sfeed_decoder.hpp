#pragma once
#include "types.hpp"
namespace alosmm {
class SFeedDecoder {
public:
    void set_price_divider(int8_t exchange_id,double divider){dividers_[exchange_id]=divider>0?divider:100.0;}
    std::vector<Book> decode_binary(std::span<const uint8_t> frame,int64_t recv_ns) const;
private:
    double divider(int8_t ex)const{auto it=dividers_.find(ex);return it==dividers_.end()?100.0:it->second;}
    std::unordered_map<int8_t,double> dividers_;
};
} // namespace alosmm
