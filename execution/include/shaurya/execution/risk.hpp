#pragma once

#include "shaurya/execution/broker_adapter.hpp"

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace shaurya::execution {

enum class RiskMappingState { Verified, Missing, Stale, Partial, Ambiguous, HashInvalid };
enum class RiskIdempotencyState { NewIntent, Duplicate, Conflict, ReconciliationRequired };

struct GreekLimits {
  std::optional<std::int64_t> maximum_absolute_delta;
  std::optional<std::int64_t> maximum_absolute_gamma;
  std::optional<std::int64_t> maximum_absolute_vega;
};

struct RiskConfiguration {
  std::string schema_version{"1.0.0"};
  std::string configuration_version;
  std::string configuration_digest;
  std::string trading_date;
  std::int64_t maximum_observation_age_ns{};
  std::int64_t maximum_mapping_age_ns{};
  std::int64_t maximum_greek_age_ns{};
  std::int64_t maximum_clock_skew_ns{};
  std::uint64_t maximum_order_quantity{};
  std::int64_t maximum_absolute_instrument_position{};
  std::uint64_t maximum_gross_premium_paise{};
  std::uint64_t maximum_outstanding_orders{};
  std::uint64_t maximum_orders_per_window{};
  std::int64_t order_rate_window_ns{};
  std::uint64_t maximum_daily_loss_paise{};
  std::uint64_t maximum_drawdown_paise{};
  GreekLimits greeks;

  [[nodiscard]] static RiskConfiguration parse(std::string_view json);
  [[nodiscard]] std::string canonical_payload() const;
};

struct WorkingRiskOrder {
  std::string internal_order_id;
  std::string canonical_instrument_id;
  std::string instrument_token;
  OrderSide side{OrderSide::Buy};
  std::uint64_t remaining_quantity{};
  std::uint64_t limit_price_paise{};
  std::uint64_t cumulative_filled_quantity{};
};

struct GreekSnapshot {
  std::string canonical_instrument_id;
  std::string source;
  std::string provenance;
  bool authoritative{};
  std::int64_t timestamp_ns{};
  std::int64_t current_delta{};
  std::int64_t current_gamma{};
  std::int64_t current_vega{};
  std::int64_t delta_per_unit{};
  std::int64_t gamma_per_unit{};
  std::int64_t vega_per_unit{};
};

struct RiskSnapshot {
  std::int64_t now_ns{};
  bool kill_switch{};
  bool ready{};
  bool reconciliation_required{};
  RiskIdempotencyState idempotency{RiskIdempotencyState::NewIntent};
  RiskMappingState mapping_state{RiskMappingState::Missing};
  std::optional<RoutingRecord> route;
  std::string route_trading_date;
  std::int64_t mapping_age_ns{};
  std::int64_t maximum_mapping_age_ns{};
  std::string expected_execution_session_id;
  std::string expected_strategy_id;
  std::string expected_strategy_run_id;
  BrokerSessionHealth broker_health{BrokerSessionHealth::Unknown};
  std::optional<MarketObservation> observation;
  std::int64_t exact_instrument_position{};
  std::int64_t exact_token_position{};
  std::uint64_t exact_token_working_sell_quantity{};
  std::uint64_t current_gross_premium_paise{};
  bool broker_positions_authoritative{};
  bool position_marks_authoritative{};
  std::vector<WorkingRiskOrder> working_orders;
  std::vector<std::int64_t> recent_order_timestamps_ns;
  std::optional<GreekSnapshot> greek_snapshot;
  std::optional<std::uint64_t> daily_loss_paise;
  std::optional<std::uint64_t> drawdown_paise;
  std::string pnl_source;
  std::string pnl_provenance;
  std::optional<std::int64_t> pnl_timestamp_ns;
  bool cancel_target_known{};
  bool cancel_target_terminal{};
  std::uint64_t cancel_target_filled_quantity{};
  bool mutation_target_known{};
  bool mutation_target_terminal{};
  std::optional<WorkingRiskOrder> mutation_target;
};

class RiskEngine {
 public:
  explicit RiskEngine(RiskConfiguration configuration);
  [[nodiscard]] RiskDecision evaluate(const OrderIntent& intent,
                                      const RiskSnapshot& snapshot) const;
  [[nodiscard]] const RiskConfiguration& configuration() const noexcept { return configuration_; }

 private:
  RiskConfiguration configuration_;
};

[[nodiscard]] bool risk_approved(const RiskDecision& decision) noexcept;

}  // namespace shaurya::execution
