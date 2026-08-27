#include "shaurya/execution/order_state_machine.hpp"

#include "shaurya/execution/canonical_json.hpp"

#include <algorithm>
#include <limits>

namespace shaurya::execution {
namespace {

JsonValue integer(std::uint64_t value) { return JsonValue(JsonInteger{std::to_string(value)}); }
JsonValue text(std::string value) { return JsonValue(std::move(value)); }

std::string evidence_fingerprint(const OrderUpdateEvidence& update) {
  JsonObject object{{"kind", integer(static_cast<std::uint64_t>(update.kind))}};
  if (update.broker_order_id) object.emplace("broker_order_id", text(*update.broker_order_id));
  if (update.cumulative_filled_quantity) {
    object.emplace("cumulative_filled_quantity", integer(*update.cumulative_filled_quantity));
  }
  if (update.accepted_quantity) {
    object.emplace("accepted_quantity", integer(*update.accepted_quantity));
  }
  if (update.accepted_limit_price_paise) {
    object.emplace("accepted_limit_price_paise", integer(*update.accepted_limit_price_paise));
  }
  return sha256_hex(canonical_json(JsonValue(std::move(object))));
}

TransitionResult refuse(const OrderAggregate& current, std::string code, bool incident = false) {
  return TransitionResult{current, false, 0, std::move(code), incident};
}

bool terminal(OrderState state) {
  return state == OrderState::Filled || state == OrderState::Cancelled ||
         state == OrderState::Rejected;
}

OrderState working_state(const OrderAggregate& aggregate) {
  return aggregate.cumulative_filled_quantity == 0 ? OrderState::Acknowledged
                                                    : OrderState::PartiallyFilled;
}

TransitionResult apply_evidence(OrderAggregate next, const OrderUpdateEvidence& update,
                                std::int64_t position_delta = 0) {
  if (!update.update_id.empty()) {
    next.applied_evidence.push_back({update.update_id, evidence_fingerprint(update)});
  }
  return TransitionResult{std::move(next), true, position_delta, std::nullopt, false};
}

}  // namespace

std::uint64_t OrderAggregate::working_quantity() const noexcept {
  return cumulative_filled_quantity >= effective_quantity
             ? 0
             : effective_quantity - cumulative_filled_quantity;
}

const char* order_state_name(OrderState state) noexcept {
  switch (state) {
    case OrderState::Prepared: return "prepared";
    case OrderState::SubmissionStarted: return "submission_started";
    case OrderState::Acknowledged: return "acknowledged";
    case OrderState::PartiallyFilled: return "partially_filled";
    case OrderState::AmbiguousSubmission: return "ambiguous_submission";
    case OrderState::ReconciliationRequired: return "reconciliation_required";
    case OrderState::Filled: return "filled";
    case OrderState::Cancelled: return "cancelled";
    case OrderState::Rejected: return "rejected";
  }
  return "unknown";
}

TransitionResult apply_order_update(const OrderAggregate& current,
                                    const OrderUpdateEvidence& update) {
  if (current.original_quantity == 0 || current.effective_quantity == 0 ||
      current.cumulative_filled_quantity > current.effective_quantity) {
    return refuse(current, "FSM_INVALID_AGGREGATE", true);
  }
  if (!update.update_id.empty()) {
    const auto existing = std::find_if(
        current.applied_evidence.begin(), current.applied_evidence.end(),
        [&](const AppliedEvidence& item) { return item.update_id == update.update_id; });
    if (existing != current.applied_evidence.end()) {
      if (existing->fingerprint == evidence_fingerprint(update)) {
        return TransitionResult{current, false, 0, std::nullopt, false};
      }
      return refuse(current, "FSM_CONFLICTING_DUPLICATE_UPDATE", true);
    }
  }

  OrderAggregate next = current;
  switch (update.kind) {
    case OrderEventKind::SubmissionStarted:
      if (current.state != OrderState::Prepared) return refuse(current, "FSM_ILLEGAL_TRANSITION");
      next.state = OrderState::SubmissionStarted;
      return apply_evidence(std::move(next), update);

    case OrderEventKind::BrokerAcknowledged:
      if (current.state != OrderState::SubmissionStarted) {
        return refuse(current, "FSM_ILLEGAL_TRANSITION", terminal(current.state));
      }
      if (!update.broker_order_id || update.broker_order_id->empty()) {
        return refuse(current, "FSM_MISSING_BROKER_ORDER_ID");
      }
      next.broker_order_id = update.broker_order_id;
      next.state = working_state(next);
      return apply_evidence(std::move(next), update);

    case OrderEventKind::BrokerRejected:
      if (current.state == OrderState::Rejected) {
        return apply_evidence(std::move(next), update);
      }
      if (current.state != OrderState::Prepared &&
          current.state != OrderState::SubmissionStarted) {
        return refuse(current, "FSM_CONTRADICTORY_REJECTION", true);
      }
      next.state = OrderState::Rejected;
      return apply_evidence(std::move(next), update);

    case OrderEventKind::FillUpdate: {
      if (current.state != OrderState::Acknowledged &&
          current.state != OrderState::PartiallyFilled) {
        if (current.state == OrderState::Filled &&
            update.cumulative_filled_quantity == current.cumulative_filled_quantity) {
          return apply_evidence(std::move(next), update);
        }
        return refuse(current, "FSM_FILL_REQUIRES_WORKING_ORDER", true);
      }
      if (!update.cumulative_filled_quantity ||
          *update.cumulative_filled_quantity < current.cumulative_filled_quantity) {
        return refuse(current, "FSM_FILL_REGRESSION", true);
      }
      if (*update.cumulative_filled_quantity > current.effective_quantity) {
        return refuse(current, "FSM_FILL_EXCEEDS_QUANTITY", true);
      }
      const auto delta = *update.cumulative_filled_quantity - current.cumulative_filled_quantity;
      if (delta == 0) return apply_evidence(std::move(next), update);
      if (delta > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())) {
        return refuse(current, "FSM_POSITION_OVERFLOW", true);
      }
      next.cumulative_filled_quantity = *update.cumulative_filled_quantity;
      if (next.cumulative_filled_quantity == next.effective_quantity) {
        next.state = OrderState::Filled;
        next.pending_mutation = PendingMutation::None;
        next.pending_modify_quantity.reset();
        next.pending_modify_limit_price_paise.reset();
      } else {
        next.state = OrderState::PartiallyFilled;
      }
      const auto signed_delta = static_cast<std::int64_t>(delta) *
                                (current.side == OrderSide::Buy ? 1 : -1);
      return apply_evidence(std::move(next), update, signed_delta);
    }

    case OrderEventKind::ModifyRequested:
      if ((current.state != OrderState::Acknowledged &&
           current.state != OrderState::PartiallyFilled) ||
          current.pending_mutation != PendingMutation::None) {
        return refuse(current, "FSM_MODIFY_NOT_AVAILABLE");
      }
      if (!update.accepted_quantity || !update.accepted_limit_price_paise ||
          *update.accepted_quantity < current.cumulative_filled_quantity ||
          *update.accepted_quantity == 0 || *update.accepted_limit_price_paise == 0) {
        return refuse(current, "FSM_INVALID_MODIFY_TERMS");
      }
      next.pending_mutation = PendingMutation::Modify;
      next.pending_modify_quantity = update.accepted_quantity;
      next.pending_modify_limit_price_paise = update.accepted_limit_price_paise;
      return apply_evidence(std::move(next), update);

    case OrderEventKind::ModifyAccepted:
      if (current.pending_mutation != PendingMutation::Modify || !update.accepted_quantity ||
          !update.accepted_limit_price_paise ||
          update.accepted_quantity != current.pending_modify_quantity ||
          update.accepted_limit_price_paise != current.pending_modify_limit_price_paise ||
          *update.accepted_quantity < current.cumulative_filled_quantity ||
          *update.accepted_quantity == 0 || *update.accepted_limit_price_paise == 0) {
        return refuse(current, "FSM_INVALID_MODIFY_ACK", true);
      }
      next.effective_quantity = *update.accepted_quantity;
      next.limit_price_paise = *update.accepted_limit_price_paise;
      next.pending_mutation = PendingMutation::None;
      next.pending_modify_quantity.reset();
      next.pending_modify_limit_price_paise.reset();
      next.state = next.cumulative_filled_quantity == next.effective_quantity
                       ? OrderState::Filled
                       : working_state(next);
      return apply_evidence(std::move(next), update);

    case OrderEventKind::ModifyRejected:
      if (current.pending_mutation != PendingMutation::Modify) {
        return refuse(current, "FSM_ILLEGAL_TRANSITION");
      }
      next.pending_mutation = PendingMutation::None;
      next.pending_modify_quantity.reset();
      next.pending_modify_limit_price_paise.reset();
      next.state = working_state(next);
      return apply_evidence(std::move(next), update);

    case OrderEventKind::CancelRequested:
      if ((current.state != OrderState::Acknowledged &&
           current.state != OrderState::PartiallyFilled) ||
          current.pending_mutation != PendingMutation::None) {
        return refuse(current, "FSM_CANCEL_NOT_AVAILABLE");
      }
      next.pending_mutation = PendingMutation::Cancel;
      next.cancel_was_requested = true;
      return apply_evidence(std::move(next), update);

    case OrderEventKind::CancelAccepted:
      if (current.state == OrderState::Filled || current.state == OrderState::Cancelled) {
        if (!current.cancel_was_requested) {
          return refuse(current, "FSM_UNSOLICITED_CANCEL_ACK", true);
        }
        return apply_evidence(std::move(next), update);
      }
      if (current.pending_mutation != PendingMutation::Cancel) {
        if (current.state == OrderState::Acknowledged ||
            current.state == OrderState::PartiallyFilled) {
          return refuse(current, "FSM_UNSOLICITED_CANCEL_ACK", true);
        }
        return refuse(current, "FSM_ILLEGAL_TRANSITION", terminal(current.state));
      }
      next.pending_mutation = PendingMutation::None;
      next.state = OrderState::Cancelled;
      return apply_evidence(std::move(next), update);

    case OrderEventKind::CancelRejected:
      if (current.pending_mutation != PendingMutation::Cancel) {
        return refuse(current, "FSM_ILLEGAL_TRANSITION");
      }
      next.pending_mutation = PendingMutation::None;
      next.state = OrderState::ReconciliationRequired;
      return apply_evidence(std::move(next), update);

    case OrderEventKind::SubmissionAmbiguous:
      if (current.state != OrderState::SubmissionStarted &&
          current.pending_mutation == PendingMutation::None) {
        return refuse(current, "FSM_ILLEGAL_TRANSITION");
      }
      next.state = current.state == OrderState::SubmissionStarted
                       ? OrderState::AmbiguousSubmission
                       : OrderState::ReconciliationRequired;
      return apply_evidence(std::move(next), update);

    case OrderEventKind::ReconcileWorking: {
      if (current.state != OrderState::AmbiguousSubmission &&
          current.state != OrderState::ReconciliationRequired) {
        return refuse(current, "FSM_RECONCILIATION_NOT_REQUIRED");
      }
      if (!update.broker_order_id || !update.cumulative_filled_quantity ||
          *update.cumulative_filled_quantity < current.cumulative_filled_quantity ||
          *update.cumulative_filled_quantity > current.effective_quantity) {
        return refuse(current, "FSM_INVALID_RECONCILIATION", true);
      }
      const auto delta = *update.cumulative_filled_quantity - current.cumulative_filled_quantity;
      if (delta > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())) {
        return refuse(current, "FSM_POSITION_OVERFLOW", true);
      }
      next.broker_order_id = update.broker_order_id;
      next.cumulative_filled_quantity = *update.cumulative_filled_quantity;
      next.pending_mutation = PendingMutation::None;
      next.pending_modify_quantity.reset();
      next.pending_modify_limit_price_paise.reset();
      next.state = next.cumulative_filled_quantity == next.effective_quantity
                       ? OrderState::Filled
                       : working_state(next);
      const auto signed_delta = static_cast<std::int64_t>(delta) *
                                (current.side == OrderSide::Buy ? 1 : -1);
      return apply_evidence(std::move(next), update, signed_delta);
    }

    case OrderEventKind::ReconcileCancelled:
    case OrderEventKind::ReconcileRejected:
      if ((update.kind == OrderEventKind::ReconcileCancelled &&
           current.state == OrderState::Cancelled) ||
          (update.kind == OrderEventKind::ReconcileRejected &&
           current.state == OrderState::Rejected)) {
        return apply_evidence(std::move(next), update);
      }
      if (current.state != OrderState::AmbiguousSubmission &&
          current.state != OrderState::ReconciliationRequired) {
        return refuse(current, "FSM_RECONCILIATION_NOT_REQUIRED");
      }
      next.pending_mutation = PendingMutation::None;
      next.state = update.kind == OrderEventKind::ReconcileCancelled ? OrderState::Cancelled
                                                                     : OrderState::Rejected;
      return apply_evidence(std::move(next), update);
  }
  return refuse(current, "FSM_UNKNOWN_EVENT");
}

}  // namespace shaurya::execution
