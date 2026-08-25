#pragma once
#include "kotak_rest.hpp"
#include "sfeed_decoder.hpp"
namespace alosmm {
class SFeedClient {
public:
    using Callback=std::function<void(const Book&)>;
    SFeedClient(const Config& cfg,const KotakSession& session,std::vector<uint32_t> tokens,Callback cb);
    void run(std::atomic<bool>& stop);
private:
    Config cfg_; KotakSession session_; std::vector<uint32_t> tokens_; Callback cb_; SFeedDecoder decoder_;
};

class OrderUpdateClient {
public:
    using Callback=std::function<void(const OrderUpdate&)>;
    OrderUpdateClient(const KotakSession&s,Callback cb):session_(s),cb_(std::move(cb)){}
    void run(std::atomic<bool>& stop);
    static std::optional<OrderUpdate> parse_message(std::string_view text,int64_t recv_ts_ns=0);
private:KotakSession session_;Callback cb_;
};
} // namespace alosmm
