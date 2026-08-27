#include "shaurya/execution/order_state_machine.hpp"

#include <array>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <limits>
#include <optional>
#include <set>
#include <string>
#include <string_view>

namespace {
using namespace shaurya::execution;
void require(bool condition, std::string_view message) {
  if (!condition) { std::cerr << message << '\n'; std::exit(1); }
}
OrderAggregate order(OrderState state = OrderState::Prepared) {
  OrderAggregate value;
  value.internal_order_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  value.canonical_instrument_id = "NSE:NSE_FNO:NIFTY:option:2026-09-03:25000:CE";
  value.route_digest = std::string(64, 'a');
  value.side = OrderSide::Buy;
  value.original_quantity = 50;
  value.effective_quantity = 50;
  value.limit_price_paise = 1250;
  value.state = state;
  if (state == OrderState::Acknowledged || state == OrderState::PartiallyFilled ||
      state == OrderState::Filled || state == OrderState::Cancelled) {
    value.broker_order_id = "paper-existing";
  }
  if (state == OrderState::PartiallyFilled || state == OrderState::ReconciliationRequired) {
    value.cumulative_filled_quantity = 10;
  }
  if (state == OrderState::Filled) {
    value.cumulative_filled_quantity = 50;
    value.cancel_was_requested = true;
  }
  if (state == OrderState::Cancelled) value.cancel_was_requested = true;
  return value;
}
OrderUpdateEvidence update(OrderEventKind kind, std::string id,
                           std::optional<std::string> broker = std::nullopt,
                           std::optional<std::uint64_t> cumulative = std::nullopt,
                           std::optional<std::uint64_t> quantity = std::nullopt,
                           std::optional<std::uint64_t> price = std::nullopt) {
  return {kind, std::move(id), std::move(broker), cumulative, quantity, price};
}
OrderUpdateEvidence matrix_update(OrderEventKind kind, OrderState state) {
  const auto cumulative = state == OrderState::Filled ? 50U : 20U;
  return update(kind, "matrix-" + std::to_string(static_cast<int>(kind)), "paper-matrix",
                cumulative, 40, 1300);
}
std::string event_name(OrderEventKind kind) {
  constexpr std::array names{"SubmissionStarted", "BrokerAcknowledged", "BrokerRejected",
      "FillUpdate", "ModifyRequested", "ModifyAccepted", "ModifyRejected", "CancelRequested",
      "CancelAccepted", "CancelRejected", "SubmissionAmbiguous", "ReconcileWorking",
      "ReconcileCancelled", "ReconcileRejected"};
  return names.at(static_cast<std::size_t>(kind));
}
std::set<std::string> legal_edges() {
  const auto path = std::filesystem::path(SHAURYA_EXECUTION_SOURCE_ROOT) /
                    "tests/fixtures/fsm/legal_edges.tsv";
  std::ifstream input(path);
  require(static_cast<bool>(input), "FSM fixture missing");
  std::set<std::string> edges;
  std::string line;
  while (std::getline(input, line)) edges.insert(line);
  require(edges.size() == 23, "FSM fixture edge count");
  return edges;
}
}  // namespace

int main() {
  using namespace shaurya::execution;
  constexpr std::array states{OrderState::Prepared, OrderState::SubmissionStarted,
      OrderState::Acknowledged, OrderState::PartiallyFilled, OrderState::AmbiguousSubmission,
      OrderState::ReconciliationRequired, OrderState::Filled, OrderState::Cancelled,
      OrderState::Rejected};
  constexpr std::array events{OrderEventKind::SubmissionStarted, OrderEventKind::BrokerAcknowledged,
      OrderEventKind::BrokerRejected, OrderEventKind::FillUpdate, OrderEventKind::ModifyRequested,
      OrderEventKind::ModifyAccepted, OrderEventKind::ModifyRejected,
      OrderEventKind::CancelRequested, OrderEventKind::CancelAccepted,
      OrderEventKind::CancelRejected, OrderEventKind::SubmissionAmbiguous,
      OrderEventKind::ReconcileWorking, OrderEventKind::ReconcileCancelled,
      OrderEventKind::ReconcileRejected};
  const auto legal = legal_edges();
  for (const auto state : states) {
    for (const auto kind : events) {
      const auto before = order(state);
      const auto result = apply_order_update(before, matrix_update(kind, state));
      const auto key = std::string(order_state_name(state)) + '\t' + event_name(kind);
      require(result.applied == legal.contains(key), "FSM matrix mismatch");
      if (!result.applied) require(result.aggregate == before, "illegal edge mutated aggregate");
    }
  }

  auto acknowledged = apply_order_update(
      apply_order_update(order(), update(OrderEventKind::SubmissionStarted, "submit")).aggregate,
      update(OrderEventKind::BrokerAcknowledged, "ack", "paper-1")).aggregate;
  const auto unsolicited = apply_order_update(
      acknowledged, update(OrderEventKind::CancelAccepted, "unsolicited"));
  require(unsolicited.incident && unsolicited.error_code == "FSM_UNSOLICITED_CANCEL_ACK" &&
              unsolicited.aggregate == acknowledged,
          "unsolicited cancel ACK accepted");

  auto modified = apply_order_update(
      acknowledged, update(OrderEventKind::ModifyRequested, "modify-request", std::nullopt,
                           std::nullopt, 40, 1300)).aggregate;
  const auto mismatched = apply_order_update(
      modified, update(OrderEventKind::ModifyAccepted, "modify-wrong", std::nullopt,
                       std::nullopt, 45, 1350));
  require(mismatched.incident && mismatched.error_code == "FSM_INVALID_MODIFY_ACK" &&
              mismatched.aggregate == modified,
          "modify ACK was not bound to requested terms");
  modified = apply_order_update(
      modified, update(OrderEventKind::FillUpdate, "fill-during-modify", std::nullopt, 20)).aggregate;
  const auto accepted = apply_order_update(
      modified, update(OrderEventKind::ModifyAccepted, "modify-correct", std::nullopt,
                       std::nullopt, 40, 1300));
  require(accepted.applied && accepted.aggregate.effective_quantity == 40 &&
              !accepted.aggregate.pending_modify_quantity,
          "matching modify ACK failed after fill");

  auto cancelling = apply_order_update(
      acknowledged, update(OrderEventKind::CancelRequested, "cancel-request")).aggregate;
  cancelling = apply_order_update(
      cancelling, update(OrderEventKind::CancelAccepted, "cancel-ack")).aggregate;
  const auto repeated_cancel = apply_order_update(
      cancelling, update(OrderEventKind::CancelAccepted, "cancel-confirmation-2"));
  require(repeated_cancel.applied && repeated_cancel.aggregate.state == OrderState::Cancelled,
          "compatible repeated cancellation rejected");
  auto rejected = apply_order_update(order(), update(OrderEventKind::BrokerRejected, "reject-1"));
  const auto repeated_reject = apply_order_update(
      rejected.aggregate, update(OrderEventKind::BrokerRejected, "reject-2"));
  require(repeated_reject.applied && repeated_reject.aggregate.state == OrderState::Rejected,
          "compatible repeated rejection rejected");

  auto race = apply_order_update(
      acknowledged, update(OrderEventKind::CancelRequested, "race-cancel")).aggregate;
  auto full = apply_order_update(
      race, update(OrderEventKind::FillUpdate, "race-fill", std::nullopt, 50));
  require(full.applied && full.signed_position_delta == 50 &&
              full.aggregate.state == OrderState::Filled,
          "fill did not win cancel race");
  const auto late_cancel = apply_order_update(
      full.aggregate, update(OrderEventKind::CancelAccepted, "race-cancel-ack"));
  require(late_cancel.applied && late_cancel.aggregate.state == OrderState::Filled,
          "compatible late cancel changed filled state");

  const auto duplicate_fill = apply_order_update(
      full.aggregate, update(OrderEventKind::FillUpdate, "race-fill", std::nullopt, 50));
  require(!duplicate_fill.applied && !duplicate_fill.error_code,
          "identical fill update was not idempotent");
  const auto conflicting_fill = apply_order_update(
      full.aggregate, update(OrderEventKind::FillUpdate, "race-fill", std::nullopt, 49));
  require(conflicting_fill.incident &&
              conflicting_fill.error_code == "FSM_CONFLICTING_DUPLICATE_UPDATE",
          "conflicting duplicate update was accepted");

  auto huge = order(OrderState::Acknowledged);
  huge.original_quantity = std::numeric_limits<std::uint64_t>::max();
  huge.effective_quantity = huge.original_quantity;
  const auto overflow = apply_order_update(
      huge, update(OrderEventKind::FillUpdate, "overflow", std::nullopt,
                   static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) + 1U));
  require(overflow.incident && overflow.error_code == "FSM_POSITION_OVERFLOW",
          "position overflow accepted");
}
