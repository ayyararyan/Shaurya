#include "alosmm/sfeed_client.hpp"
#include <cassert>
int main(){
    const std::string msg=R"({"type":"order","data":{"nOrdNo":"260216000308219","ordSt":"complete","avgPrc":"35.88","qty":65,"fldQty":65,"unFldSz":0,"sym":"NIFTY","trdSym":"NIFTY26AUG24300PE","tok":"123456","trnsTp":"B"}})";
    auto u=alosmm::OrderUpdateClient::parse_message(msg,123);
    assert(u);assert(u->order_id=="260216000308219");assert(u->status=="complete");assert(u->symbol=="NIFTY26AUG24300PE");assert(u->token==123456);assert(u->side==alosmm::Side::Buy);assert(u->filled_qty==65);assert(std::abs(u->avg_price-35.88)<1e-9);assert(u->recv_ts_ns==123);
    auto x=alosmm::OrderUpdateClient::parse_message(R"({"type":"position","data":{}})",123);assert(!x);
    return 0;
}
