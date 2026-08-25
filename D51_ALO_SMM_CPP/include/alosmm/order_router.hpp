#pragma once
#include "kotak_rest.hpp"
#include "spsc_ring.hpp"
namespace alosmm {
class LiveGate {
public:
    static bool compiled(){return ALO_ENABLE_LIVE_ROUTER==1;}
    static void require(const Config& cfg);
};
class OrderRouter {
public:
    OrderRouter(const Config&cfg,const KotakSession&s);~OrderRouter();
    void start();void stop();bool submit_desired(const OrderIntent&i);void on_order_update(const OrderUpdate&u);
    uint64_t rejected_by_queue()const{return rejected_.load();}
private:
    struct Working{std::string id;double price{0};int qty{0};std::string symbol;uint32_t token{0};};
    void run();void rate_limit();size_t key(CP c,Side s)const{return static_cast<size_t>(c)*2+static_cast<size_t>(s);}
    const Config&cfg_;KotakSession session_;KotakRestClient rest_;SpscRing<OrderIntent,1024>q_;SpscRing<OrderUpdate,1024>updates_;std::atomic<bool>running_{false};std::thread th_;std::atomic<uint64_t>rejected_{0};std::array<Working,4>working_{};std::deque<Clock::time_point>sent_;
};
} // namespace alosmm
