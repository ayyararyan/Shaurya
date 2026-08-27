#pragma once

#include "shaurya/execution/contracts.hpp"
#include "shaurya/execution/routing_snapshot.hpp"

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace shaurya::execution {

enum class BrokerMutationStatus { Acknowledged, Rejected, Ambiguous };
enum class BrokerQueryStatus { Authoritative, Partial, Unavailable };
enum class BrokerSessionHealth { Ready, Degraded, Lost, Unknown };

struct BrokerError {
  std::string category;
  std::optional<unsigned> http_status;
  std::string correlation_id;
  friend bool operator==(const BrokerError&, const BrokerError&) = default;
};

struct BrokerOrderRequest {
  std::string internal_order_id;
  std::string intent_id;
  RoutingRecord route;
  OrderSide side{OrderSide::Buy};
  std::uint64_t quantity{};
  std::uint64_t limit_price_paise{};
  std::int64_t submitted_at_ns{};
  std::uint64_t baseline_cumulative_volume{};
};

struct BrokerModifyRequest {
  std::string internal_order_id;
  std::uint64_t quantity{};
  std::uint64_t limit_price_paise{};
};

struct BrokerMutationResult {
  BrokerMutationStatus status{BrokerMutationStatus::Ambiguous};
  std::string internal_order_id;
  std::optional<std::string> broker_correlation_id;
  std::string provenance;
  std::optional<BrokerError> error;
  bool terminal_state_confirmed{};
  std::optional<std::uint64_t> accepted_quantity;
  std::optional<std::uint64_t> accepted_limit_price_paise;

  BrokerMutationResult() = default;
  BrokerMutationResult(BrokerMutationStatus status_value, std::string internal_id,
                       std::optional<std::string> broker_id, std::string provenance_value,
                       std::optional<BrokerError> error_value,
                       bool terminal_confirmed = false,
                       std::optional<std::uint64_t> accepted_quantity_value = std::nullopt,
                       std::optional<std::uint64_t> accepted_price_value = std::nullopt)
      : status(status_value), internal_order_id(std::move(internal_id)),
        broker_correlation_id(std::move(broker_id)), provenance(std::move(provenance_value)),
        error(std::move(error_value)), terminal_state_confirmed(terminal_confirmed),
        accepted_quantity(accepted_quantity_value),
        accepted_limit_price_paise(accepted_price_value) {}
};

struct BrokerOrderSnapshot {
  std::string internal_order_id;
  std::string canonical_instrument_id;
  std::string instrument_token;
  OrderSide side{OrderSide::Buy};
  std::uint64_t quantity{};
  std::uint64_t limit_price_paise{};
  std::uint64_t cumulative_filled_quantity{};
  std::string state;
  std::string provenance;
  friend bool operator==(const BrokerOrderSnapshot&, const BrokerOrderSnapshot&) = default;
};

struct BrokerFillSnapshot {
  std::string fill_id;
  std::string internal_order_id;
  std::string canonical_instrument_id;
  std::string instrument_token;
  std::uint64_t cumulative_filled_quantity{};
  std::uint64_t last_fill_quantity{};
  std::uint64_t fill_price_paise{};
  std::int64_t evidence_timestamp_ns{};
  std::string provenance;
  friend bool operator==(const BrokerFillSnapshot&, const BrokerFillSnapshot&) = default;
};

struct BrokerPositionSnapshot {
  std::string canonical_instrument_id;
  std::string instrument_token;
  std::int64_t quantity{};
  std::string provenance;
  friend bool operator==(const BrokerPositionSnapshot&, const BrokerPositionSnapshot&) = default;
};

struct BrokerPnlSnapshot {
  BrokerQueryStatus status{BrokerQueryStatus::Unavailable};
  std::int64_t timestamp_ns{};
  std::uint64_t daily_loss_paise{};
  std::uint64_t drawdown_paise{};
  std::string source;
  std::string provenance;
};

struct BrokerGreekSnapshot {
  BrokerQueryStatus status{BrokerQueryStatus::Unavailable};
  std::string canonical_instrument_id;
  std::int64_t timestamp_ns{};
  std::int64_t current_delta{};
  std::int64_t current_gamma{};
  std::int64_t current_vega{};
  std::int64_t delta_per_unit{};
  std::int64_t gamma_per_unit{};
  std::int64_t vega_per_unit{};
  std::string source;
  std::string provenance;
};

template <typename T>
struct BrokerQueryResult {
  BrokerQueryStatus status{BrokerQueryStatus::Unavailable};
  std::vector<T> items;
  std::string provenance;
  [[nodiscard]] bool authoritative() const noexcept {
    return status == BrokerQueryStatus::Authoritative;
  }
};

class BrokerAdapter {
 public:
  virtual ~BrokerAdapter() = default;
  [[nodiscard]] virtual bool shutdown_operations_bounded_nonblocking() const noexcept {
    return false;
  }
  [[nodiscard]] virtual BrokerMutationResult place(const BrokerOrderRequest& request) = 0;
  [[nodiscard]] virtual BrokerMutationResult modify(const BrokerModifyRequest& request) = 0;
  [[nodiscard]] virtual BrokerMutationResult cancel(std::string_view internal_order_id) = 0;
  [[nodiscard]] virtual BrokerQueryResult<BrokerOrderSnapshot> query_orders() const = 0;
  [[nodiscard]] virtual BrokerQueryResult<BrokerFillSnapshot> query_trades() const = 0;
  [[nodiscard]] virtual BrokerQueryResult<BrokerPositionSnapshot> query_positions() const = 0;
  [[nodiscard]] virtual BrokerSessionHealth session_health() const noexcept = 0;
  [[nodiscard]] virtual BrokerPnlSnapshot query_pnl() const { return {}; }
  [[nodiscard]] virtual BrokerGreekSnapshot query_greeks(std::string_view canonical_instrument_id) const {
    (void)canonical_instrument_id;
    return {};
  }
  [[nodiscard]] virtual std::vector<BrokerFillSnapshot> accept_observation(
      const MarketObservation& observation) {
    (void)observation;
    return {};
  }
};

}  // namespace shaurya::execution
