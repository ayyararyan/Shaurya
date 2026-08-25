#pragma once
#include "common.hpp"
namespace alosmm {
template <class T, size_t N> class SpscRing {
    static_assert((N & (N-1))==0, "N must be a power of two");
public:
    bool push(const T& v) {
        const size_t h=head_.load(std::memory_order_relaxed); const size_t n=(h+1)&(N-1);
        if(n==tail_.load(std::memory_order_acquire)) return false;
        data_[h]=v; head_.store(n,std::memory_order_release); return true;
    }
    bool pop(T& out) {
        const size_t t=tail_.load(std::memory_order_relaxed);
        if(t==head_.load(std::memory_order_acquire)) return false;
        out=data_[t]; tail_.store((t+1)&(N-1),std::memory_order_release); return true;
    }
    [[nodiscard]] bool empty() const { return head_.load(std::memory_order_acquire)==tail_.load(std::memory_order_acquire); }
private:
    alignas(64) std::atomic<size_t> head_{0}; alignas(64) std::atomic<size_t> tail_{0}; std::array<T,N> data_{};
};
}
