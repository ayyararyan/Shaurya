#pragma once

#include "shaurya/execution/contracts.hpp"

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace shaurya::execution {

enum class OrderState {
  Prepared,
  SubmissionStarted,
  Acknowledged,
  PartiallyFilled,
  AmbiguousSubmission,
  ReconciliationRequired,
  Filled,
  Cancelled,
  Rejected,
};

enum class PendingMutation { None, Modify, Cancel };

enum class OrderEventKind {
  SubmissionStarted,
  BrokerAcknowledged,
  BrokerRejected,
  FillUpdate,
  ModifyRequested,
  ModifyAccepted,
  ModifyRejected,
  CancelRequested,
  CancelAccepted,
  CancelRejected,
  SubmissionAmbiguous,
  ReconcileWorking,
  ReconcileCancelled,
  ReconcileRejected,
};

struct OrderUpdateEvidence {
  OrderEventKind kind{OrderEventKind::SubmissionStarted};
  std::string update_id;
  std::optional<std::string> broker_order_id;
  std::optional<std::uint64_t> cumulative_filled_quantity;
  std::optional<std::uint64_t> accepted_quantity;
  std::optional<std::uint64_t> accepted_limit_price_paise;
};

struct AppliedEvidence {
  std::string update_id;
  std::string fingerprint;
  friend bool operator==(const AppliedEvidence&, const AppliedEvidence&) = default;
};

struct OrderAggregate {
  std::string internal_order_id;
  std::string canonical_instrument_id;
  std::string route_digest;
  OrderSide side{OrderSide::Buy};
  std::uint64_t original_quantity{};
  std::uint64_t effective_quantity{};
  std::uint64_t limit_price_paise{};
  std::uint64_t cumulative_filled_quantity{};
  OrderState state{OrderState::Prepared};
  PendingMutation pending_mutation{PendingMutation::None};
  std::optional<std::uint64_t> pending_modify_quantity;
  std::optional<std::uint64_t> pending_modify_limit_price_paise;
  bool cancel_was_requested{};
  std::optional<std::string> broker_order_id;
  std::vector<AppliedEvidence> applied_evidence;

  [[nodiscard]] std::uint64_t working_quantity() const noexcept;
  friend bool operator==(const OrderAggregate&, const OrderAggregate&) = default;
};

struct TransitionResult {
  OrderAggregate aggregate;
  bool applied{};
  std::int64_t signed_position_delta{};
  std::optional<std::string> error_code;
  bool incident{};
};

[[nodiscard]] TransitionResult apply_order_update(const OrderAggregate& current,
                                                  const OrderUpdateEvidence& update);
[[nodiscard]] const char* order_state_name(OrderState state) noexcept;

}  // namespace shaurya::execution
