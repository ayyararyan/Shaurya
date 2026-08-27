#include "shaurya/execution/ledger_replay.hpp"

#include <limits>
#include <utility>

namespace shaurya::execution {
namespace {
const JsonValue& field(const ExecutionEvent& event, std::string_view name) {
  const auto found = event.payload.find(name);
  if (found == event.payload.end()) throw LedgerError("replay_missing_payload_field");
  return found->second;
}
std::string string_field(const ExecutionEvent& event, std::string_view name) {
  try { return json_string(field(event, name), name); }
  catch (const JsonError&) { throw LedgerError("replay_invalid_payload_field"); }
}
std::uint64_t uint_field(const ExecutionEvent& event, std::string_view name) {
  try { return json_uint64(field(event, name), name); }
  catch (const JsonError&) { throw LedgerError("replay_invalid_payload_field"); }
}
void record_broker_source(ReconstructedState& state, const ExecutionEvent& event) {
  if (!event.payload.contains("source_fingerprint")) return;
  const auto sequence = uint_field(event, "source_sequence");
  const auto update_id = string_field(event, "update_id");
  const auto fingerprint = string_field(event, "source_fingerprint");
  static_cast<void>(string_field(event, "source_provenance"));
  const auto [existing, inserted] = state.broker_update_fingerprints.emplace(
      update_id, fingerprint);
  if (!inserted && existing->second != fingerprint)
    throw LedgerError("replay_broker_update_fingerprint_conflict");
  if (sequence != 0U) {
    if (sequence <= state.last_broker_update_sequence)
      throw LedgerError("replay_broker_update_sequence_fault");
    state.last_broker_update_sequence = sequence;
  }
}
std::string required_id(const std::optional<std::string>& value, std::string_view code) {
  if (!value) throw LedgerError(std::string(code));
  return *value;
}
OrderAggregate& required_order(ReconstructedState& state, const ExecutionEvent& event) {
  const auto found = state.orders.find(required_id(event.internal_order_id, "replay_missing_order_id"));
  if (found == state.orders.end()) throw LedgerError("replay_unknown_order");
  return found->second;
}
void update_intent(ReconstructedState& state, const ExecutionEvent& event,
                   std::string disposition, bool ambiguous = false) {
  if (!event.intent_id) return;
  const auto found = state.intents.find(*event.intent_id);
  if (found == state.intents.end()) throw LedgerError("replay_unknown_intent");
  found->second.disposition = std::move(disposition);
  if (event.internal_order_id) found->second.internal_order_id = event.internal_order_id;
  found->second.ambiguous = ambiguous;
}
void record_risk_decision(ReconstructedState& state, const ExecutionEvent& event) {
  if (!event.intent_id) throw LedgerError("replay_missing_intent_id");
  const auto found = state.intents.find(*event.intent_id);
  if (found == state.intents.end()) throw LedgerError("replay_unknown_intent");
  std::string serialized;
  try { serialized = canonical_json(field(event, "risk_decision")); }
  catch (const JsonError&) { throw LedgerError("replay_invalid_risk_decision"); }
  if (found->second.risk_decision_json && *found->second.risk_decision_json != serialized)
    throw LedgerError("replay_risk_decision_conflict");
  found->second.risk_decision_json = std::move(serialized);
}
void record_broker_outcome(ReconstructedState& state, const ExecutionEvent& event) {
  if (!event.intent_id) throw LedgerError("replay_missing_intent_id");
  const auto found = state.intents.find(*event.intent_id);
  if (found == state.intents.end()) throw LedgerError("replay_unknown_intent");
  IntentBrokerOutcomeReplay outcome;
  outcome.event_type = event.event_type;
  outcome.update_id = string_field(event, "update_id");
  outcome.source_provenance = string_field(event, "source_provenance");
  outcome.source_fingerprint = string_field(event, "source_fingerprint");
  outcome.timestamp_ns = event.timestamp_ns;
  if (event.event_type == "broker_acknowledged")
    outcome.broker_order_id = string_field(event, "broker_order_id");
  if (event.event_type == "modified") {
    outcome.accepted_quantity = uint_field(event, "quantity");
    outcome.accepted_limit_price_paise = uint_field(event, "limit_price_paise");
  }
  if (event.event_type == "modify_rejected" || event.event_type == "cancel_rejected" ||
      event.event_type == "broker_rejected" || event.event_type == "ambiguous_submission")
    outcome.error_code = string_field(event, "error_code");
  if (found->second.broker_outcome) return;
  found->second.broker_outcome = std::move(outcome);
}
TransitionResult apply(ReconstructedState& state, const ExecutionEvent& event,
                       OrderUpdateEvidence evidence) {
  auto& aggregate = required_order(state, event);
  auto result = apply_order_update(aggregate, evidence);
  if (result.error_code) {
    if (result.incident) state.incidents.push_back(*result.error_code);
    throw LedgerError(*result.error_code);
  }
  aggregate = result.aggregate;
  return result;
}
void add_checked_position(std::map<std::string, std::int64_t>& positions,
                          std::string_view key, std::int64_t delta) {
  auto& position = positions[std::string(key)];
  if ((delta > 0 && position > std::numeric_limits<std::int64_t>::max() - delta) ||
      (delta < 0 && position < std::numeric_limits<std::int64_t>::min() - delta)) {
    throw LedgerError("replay_position_overflow");
  }
  position += delta;
}
void add_position(ReconstructedState& state, std::string_view instrument, std::int64_t delta) {
  add_checked_position(state.positions, instrument, delta);
}
void add_route_position(ReconstructedState& state, const ExecutionEvent& event,
                        std::int64_t delta) {
  if (!event.internal_order_id) return;
  const auto route = state.order_route_tokens.find(*event.internal_order_id);
  if (route != state.order_route_tokens.end()) {
    add_checked_position(state.route_positions, route->second, delta);
  }
}
void replay_record(ReconstructedState& state, const LedgerRecord& record) {
    const auto& event = record.event;
    record_broker_source(state, event);
    if (event.event_type == "intent_received") {
      const auto intent_id = required_id(event.intent_id, "replay_missing_intent_id");
      const auto fingerprint = string_field(event, "semantic_fingerprint");
      const auto [found, inserted] = state.intents.emplace(
          intent_id, IntentReplayState{fingerprint, record.sequence, "received", std::nullopt,
                                       false, *event.strategy_id, *event.strategy_run_id,
                                       std::nullopt, std::nullopt});
      if (!inserted && found->second.semantic_fingerprint != fingerprint) {
        state.incidents.push_back("idempotency_conflict");
        state.safety_stopped = true;
        throw LedgerError("replay_idempotency_conflict");
      }
    } else if (event.event_type == "mapping_validated") {
      update_intent(state, event, "mapped");
      const auto order_id = required_id(event.internal_order_id, "replay_missing_order_id");
      const auto token = string_field(event, "instrument_token");
      const auto [found, inserted] = state.order_route_tokens.emplace(order_id, token);
      if (!inserted && found->second != token) throw LedgerError("replay_route_token_conflict");
    }
    else if (event.event_type == "mapping_refused") update_intent(state, event, "mapping_refused");
    else if (event.event_type == "risk_approved") {
      record_risk_decision(state, event);
      update_intent(state, event, "risk_approved");
    }
    else if (event.event_type == "risk_rejected") {
      record_risk_decision(state, event);
      update_intent(state, event, "risk_rejected");
    }
    else if (event.event_type == "submission_started") {
      const auto order_id = required_id(event.internal_order_id, "replay_missing_order_id");
      OrderAggregate aggregate;
      aggregate.internal_order_id = order_id;
      aggregate.canonical_instrument_id = string_field(event, "canonical_instrument_id");
      aggregate.route_digest = string_field(event, "route_digest");
      const auto side = string_field(event, "side");
      if (side != "BUY" && side != "SELL") throw LedgerError("replay_invalid_side");
      aggregate.side = side == "BUY" ? OrderSide::Buy : OrderSide::Sell;
      aggregate.original_quantity = uint_field(event, "quantity");
      aggregate.effective_quantity = aggregate.original_quantity;
      aggregate.limit_price_paise = uint_field(event, "limit_price_paise");
      auto transition = apply_order_update(
          aggregate, {OrderEventKind::SubmissionStarted, event.event_id, std::nullopt,
                      std::nullopt, std::nullopt, std::nullopt});
      if (transition.error_code) throw LedgerError(*transition.error_code);
      if (!state.orders.emplace(order_id, std::move(transition.aggregate)).second) {
        throw LedgerError("replay_duplicate_order");
      }
      update_intent(state, event, "submission_started");
      state.broker_attempt_timestamps_ns.push_back(event.timestamp_ns);
    } else if (event.event_type == "broker_acknowledged") {
      apply(state, event, {OrderEventKind::BrokerAcknowledged, string_field(event, "update_id"),
                           string_field(event, "broker_order_id"), std::nullopt, std::nullopt,
                           std::nullopt});
      update_intent(state, event, "acknowledged");
      record_broker_outcome(state, event);
    } else if (event.event_type == "partially_filled" || event.event_type == "filled") {
      const auto instrument = required_order(state, event).canonical_instrument_id;
      const auto transition = apply(
          state, event, {OrderEventKind::FillUpdate, string_field(event, "update_id"),
                         std::nullopt, uint_field(event, "cumulative_filled_quantity"),
                         std::nullopt, std::nullopt});
      add_position(state, instrument, transition.signed_position_delta);
      add_route_position(state, event, transition.signed_position_delta);
      update_intent(state, event, event.event_type == "filled" ? "filled" : "partially_filled");
    } else if (event.event_type == "cancel_requested") {
      apply(state, event, {OrderEventKind::CancelRequested, string_field(event, "update_id"),
                           std::nullopt, std::nullopt, std::nullopt, std::nullopt});
      update_intent(state, event, "cancel_requested");
    } else if (event.event_type == "modify_requested") {
      apply(state, event, {OrderEventKind::ModifyRequested, string_field(event, "update_id"),
                           std::nullopt, std::nullopt, uint_field(event, "quantity"),
                           uint_field(event, "limit_price_paise")});
      update_intent(state, event, "modify_requested");
      state.broker_attempt_timestamps_ns.push_back(event.timestamp_ns);
    } else if (event.event_type == "modified") {
      apply(state, event, {OrderEventKind::ModifyAccepted, string_field(event, "update_id"),
                           std::nullopt, std::nullopt, uint_field(event, "quantity"),
                           uint_field(event, "limit_price_paise")});
      update_intent(state, event, "modified");
      record_broker_outcome(state, event);
    } else if (event.event_type == "modify_rejected") {
      apply(state, event, {OrderEventKind::ModifyRejected, string_field(event, "update_id"),
                           std::nullopt, std::nullopt, std::nullopt, std::nullopt});
      update_intent(state, event, "modify_rejected");
      record_broker_outcome(state, event);
    } else if (event.event_type == "cancel_rejected") {
      apply(state, event, {OrderEventKind::CancelRejected, string_field(event, "update_id"),
                           std::nullopt, std::nullopt, std::nullopt, std::nullopt});
      update_intent(state, event, "cancel_rejected", true);
      record_broker_outcome(state, event);
      state.reconciliation_required = true;
    } else if (event.event_type == "cancelled") {
      apply(state, event, {OrderEventKind::CancelAccepted, string_field(event, "update_id"),
                           std::nullopt, std::nullopt, std::nullopt, std::nullopt});
      update_intent(state, event, "cancelled");
      record_broker_outcome(state, event);
    } else if (event.event_type == "broker_rejected") {
      apply(state, event, {OrderEventKind::BrokerRejected, string_field(event, "update_id"),
                           std::nullopt, std::nullopt, std::nullopt, std::nullopt});
      update_intent(state, event, "rejected");
      record_broker_outcome(state, event);
    } else if (event.event_type == "ambiguous_submission") {
      apply(state, event, {OrderEventKind::SubmissionAmbiguous, string_field(event, "update_id"),
                           std::nullopt, std::nullopt, std::nullopt, std::nullopt});
      update_intent(state, event, "ambiguous_submission", true);
      record_broker_outcome(state, event);
      state.reconciliation_required = true;
      state.incidents.push_back("ambiguous_submission");
    } else if (event.event_type == "reconciliation_required") {
      state.reconciliation_required = true;
      if (event.intent_id) update_intent(state, event, "reconciliation_required", true);
      else state.global_reconciliation_required = true;
      state.incidents.push_back("reconciliation_required");
    } else if (event.event_type == "reconciliation_completed") {
      if (event.internal_order_id) {
        const auto authoritative = string_field(event, "authoritative_state");
        OrderUpdateEvidence evidence;
        evidence.update_id = string_field(event, "update_id");
        if (authoritative == "working") {
          evidence.kind = OrderEventKind::ReconcileWorking;
          evidence.broker_order_id = string_field(event, "broker_order_id");
          evidence.cumulative_filled_quantity = uint_field(event, "cumulative_filled_quantity");
        } else if (authoritative == "cancelled") {
          evidence.kind = OrderEventKind::ReconcileCancelled;
        } else if (authoritative == "rejected") {
          evidence.kind = OrderEventKind::ReconcileRejected;
        } else {
          throw LedgerError("replay_invalid_authoritative_state");
        }
        const auto instrument = required_order(state, event).canonical_instrument_id;
        const auto transition = apply(state, event, std::move(evidence));
        add_position(state, instrument, transition.signed_position_delta);
        add_route_position(state, event, transition.signed_position_delta);
        update_intent(state, event, order_state_name(transition.aggregate.state), false);
      }
      if (!event.intent_id) state.global_reconciliation_required = false;
      state.reconciliation_required = state.global_reconciliation_required;
      for (const auto& [unused, intent] : state.intents) {
        static_cast<void>(unused);
        if (intent.ambiguous) state.reconciliation_required = true;
      }
    }
    else if (event.event_type == "safety_stop") {
      state.safety_stopped = true;
      state.incidents.push_back("safety_stop");
    } else if (event.event_type == "session_started") state.session_state = "started";
    else if (event.event_type == "session_stopping") state.session_state = "stopping";
    else if (event.event_type == "session_stopped") state.session_state = "stopped";
    else if (event.event_type == "ledger_repair_recorded") {
      state.reconciliation_required = true;
      state.global_reconciliation_required = true;
      state.incidents.push_back("ledger_repair_recorded");
    }
}
}  // namespace

ReconstructedState replay_ledger(const LedgerVerificationResult& verification) {
  if (!verification.clean() || verification.records.size() != verification.verified_records) {
    throw LedgerError("ledger_records_not_retained");
  }
  ReconstructedState state;
  for (const auto& record : verification.records) replay_record(state, record);
  return state;
}
ReconstructedState replay_ledger(const std::filesystem::path& path) {
  ReconstructedState state;
  const auto verification = visit_verified_ledger(path, [&](const LedgerRecord& record) {
    replay_record(state, record);
  });
  if (!verification.clean()) throw LedgerError("ledger_not_clean");
  return state;
}
}  // namespace shaurya::execution
