#pragma once

#include "shaurya/execution/broker_adapter.hpp"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <map>
#include <string>
#include <string_view>
#include <vector>

#ifndef SHAURYA_ENABLE_KOTAK_LIVE
#error "SHAURYA_ENABLE_KOTAK_LIVE must be defined by the ordinary execution target"
#endif
static_assert(SHAURYA_ENABLE_KOTAK_LIVE == 0,
              "Kotak live transport is forbidden in this delivery");

namespace shaurya::execution {

enum class KotakFixtureOperation { Place, Modify, Cancel };

struct KotakFixtureRequest {
  KotakFixtureOperation operation{KotakFixtureOperation::Place};
  std::string correlation_id;
  std::string canonical_body;
};

struct KotakParsedUpdate {
  std::uint64_t sequence{};
  std::string update_id;
  std::string internal_order_id;
  std::string state;
  std::uint64_t cumulative_filled_quantity{};
  std::string provenance{"sanitized_fixture"};
};

class KotakFixtureCodec {
 public:
  [[nodiscard]] static KotakFixtureRequest build_place(const BrokerOrderRequest& request,
                                                       std::string correlation_id);
  [[nodiscard]] static KotakFixtureRequest build_modify(const BrokerModifyRequest& request,
                                                        const RoutingRecord& route,
                                                        OrderSide side,
                                                        std::string correlation_id);
  [[nodiscard]] static KotakFixtureRequest build_cancel(std::string_view internal_order_id,
                                                        const RoutingRecord& route,
                                                        std::string correlation_id);
  [[nodiscard]] static BrokerMutationResult parse_mutation_response(
      std::string_view internal_order_id, std::string_view correlation_id,
      unsigned http_status, std::string_view sanitized_body);
  [[nodiscard]] static KotakParsedUpdate parse_update(std::string_view sanitized_body);
  [[nodiscard]] static constexpr bool live_transport_available() noexcept { return false; }
  static void require_live_mode(bool requested);
};

class KotakFixtureUpdateQueue {
 public:
  explicit KotakFixtureUpdateQueue(std::size_t maximum_depth);
  [[nodiscard]] bool push(KotakParsedUpdate update);
  [[nodiscard]] std::vector<KotakParsedUpdate> drain();
  [[nodiscard]] bool safety_stopped() const noexcept { return safety_stopped_; }

 private:
  std::size_t maximum_depth_{};
  std::uint64_t last_sequence_{};
  bool safety_stopped_{};
  std::map<std::string, std::string> update_fingerprints_;
  std::vector<KotakParsedUpdate> queued_;
};

}  // namespace shaurya::execution
