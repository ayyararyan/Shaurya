#pragma once

#include "shaurya/execution/canonical_json.hpp"

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace shaurya::execution {

inline constexpr std::string_view kContractVersion = "1.0.0";

enum class IntentAction { Place, Modify, Cancel };
enum class OrderSide { Buy, Sell };

struct OrderIntent {
  std::string intent_id;
  std::string strategy_id;
  std::string strategy_run_id;
  std::string execution_session_id;
  std::int64_t created_at_ns{};
  std::int64_t expires_at_ns{};
  std::string canonical_instrument_id;
  IntentAction action{IntentAction::Place};
  std::optional<OrderSide> side;
  std::optional<std::uint64_t> quantity;
  std::optional<std::uint64_t> limit_price_paise;
  std::optional<std::string> product;
  std::optional<std::string> time_in_force;
  std::optional<std::string> target_internal_order_id;
  std::optional<std::string> strategy_tag;

  [[nodiscard]] static OrderIntent parse(std::string_view json);
  [[nodiscard]] std::string to_json() const;
  [[nodiscard]] std::string semantic_fingerprint() const;
  friend bool operator==(const OrderIntent&, const OrderIntent&) = default;
};

struct ExecutionEvent {
  std::string event_id;
  std::string event_type;
  std::int64_t timestamp_ns{};
  std::string execution_session_id;
  std::optional<std::string> strategy_id;
  std::optional<std::string> strategy_run_id;
  std::optional<std::string> intent_id;
  std::optional<std::string> internal_order_id;
  JsonObject payload;

  [[nodiscard]] static ExecutionEvent parse(std::string_view json);
  [[nodiscard]] std::string to_json() const;
  friend bool operator==(const ExecutionEvent&, const ExecutionEvent&) = default;
};

struct RuleCheck {
  std::string rule;
  std::string outcome;
  std::int64_t before_value{};
  std::int64_t projected_value{};
  std::int64_t limit_value{};
  std::string unit;
  friend bool operator==(const RuleCheck&, const RuleCheck&) = default;
};

struct RiskDecision {
  std::string decision_id;
  std::string intent_id;
  std::string decision;
  std::int64_t timestamp_ns{};
  std::string rule_set_version;
  std::string configuration_digest;
  std::vector<RuleCheck> rules_checked;
  std::optional<std::string> rejection_code;
  std::optional<std::string> rejection_reason;
  std::int64_t mapping_age_ns{};
  std::int64_t market_age_ns{};
  std::string session_state;

  [[nodiscard]] static RiskDecision parse(std::string_view json);
  [[nodiscard]] std::string to_json() const;
  friend bool operator==(const RiskDecision&, const RiskDecision&) = default;
};

struct PositionEntry {
  std::string canonical_instrument_id;
  std::string instrument_token;
  std::int64_t strategy_desired{};
  std::int64_t ledger_reconstructed{};
  std::optional<std::int64_t> broker_authoritative;
  friend bool operator==(const PositionEntry&, const PositionEntry&) = default;
};

struct PositionSnapshot {
  std::string snapshot_id;
  std::string execution_session_id;
  std::int64_t timestamp_ns{};
  std::string source;
  std::string provenance;
  std::string reconciliation_status;
  std::vector<PositionEntry> positions;

  [[nodiscard]] static PositionSnapshot parse(std::string_view json);
  [[nodiscard]] std::string to_json() const;
  friend bool operator==(const PositionSnapshot&, const PositionSnapshot&) = default;
};

struct MarketObservation {
  std::string canonical_instrument_id;
  std::optional<std::uint64_t> best_bid_paise;
  std::optional<std::uint64_t> best_ask_paise;
  std::optional<std::uint64_t> last_trade_paise;
  std::uint64_t cumulative_volume{};
  std::optional<std::int64_t> exchange_timestamp_ns;
  std::int64_t receive_timestamp_ns{};
  std::string source;
  std::string provenance;
  std::vector<std::string> quality_flags;

  [[nodiscard]] static MarketObservation parse(std::string_view json);
  [[nodiscard]] std::string to_json() const;
  friend bool operator==(const MarketObservation&, const MarketObservation&) = default;
};

[[nodiscard]] bool is_canonical_uuid(std::string_view value);
[[nodiscard]] bool is_canonical_instrument_id(std::string_view value);

}  // namespace shaurya::execution
