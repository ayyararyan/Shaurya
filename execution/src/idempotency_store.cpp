#include "shaurya/execution/idempotency_store.hpp"

namespace shaurya::execution {
namespace {
std::string fingerprint_payload(const ExecutionEvent& event) {
  const auto found = event.payload.find("semantic_fingerprint");
  if (found == event.payload.end()) throw LedgerError("idempotency_missing_fingerprint");
  try { return json_string(found->second, "semantic_fingerprint"); }
  catch (const JsonError&) { throw LedgerError("idempotency_invalid_fingerprint"); }
}
void validate_received(const OrderIntent& intent, const ExecutionEvent& event,
                       std::string_view fingerprint) {
  if (event.event_type != "intent_received" || event.intent_id != intent.intent_id ||
      event.strategy_id != intent.strategy_id || event.strategy_run_id != intent.strategy_run_id ||
      event.execution_session_id != intent.execution_session_id || event.internal_order_id ||
      fingerprint_payload(event) != fingerprint) {
    throw LedgerError("idempotency_invalid_received_event");
  }
}
void validate_conflict(const OrderIntent& intent, const ExecutionEvent& event) {
  if (event.event_type != "safety_stop" || event.intent_id != intent.intent_id ||
      event.strategy_id != intent.strategy_id || event.strategy_run_id != intent.strategy_run_id ||
      event.execution_session_id != intent.execution_session_id) {
    throw LedgerError("idempotency_invalid_conflict_event");
  }
}
}  // namespace

IdempotencyStore IdempotencyStore::from_reconstructed(const ReconstructedState& state) {
  IdempotencyStore store;
  store.intents_ = state.intents;
  store.safety_stopped_ = state.safety_stopped;
  return store;
}

IdempotencyResult IdempotencyStore::check(const OrderIntent& intent) const {
  const auto found = intents_.find(intent.intent_id);
  if (found != intents_.end()) {
    if (found->second.semantic_fingerprint != intent.semantic_fingerprint()) {
      return {IdempotencyOutcome::Conflict, found->second.disposition,
              found->second.internal_order_id};
    }
    if (found->second.ambiguous) {
      return {IdempotencyOutcome::ReconciliationRequired, found->second.disposition,
              found->second.internal_order_id};
    }
    return {IdempotencyOutcome::Duplicate, found->second.disposition,
            found->second.internal_order_id};
  }
  if (safety_stopped_) return {IdempotencyOutcome::SafetyStopped, "safety_stop", std::nullopt};
  return {IdempotencyOutcome::NewIntent, "received", std::nullopt};
}

void IdempotencyStore::record_durable(const OrderIntent& intent, std::uint64_t sequence) {
  const auto [unused, inserted] = intents_.emplace(
      intent.intent_id, IntentReplayState{intent.semantic_fingerprint(), sequence,
                                         "received", std::nullopt, false,
                                         intent.strategy_id, intent.strategy_run_id,
                                         std::nullopt, std::nullopt});
  static_cast<void>(unused);
  if (!inserted) throw LedgerError("idempotency_already_recorded");
}

void IdempotencyStore::record_conflict_durable() { safety_stopped_ = true; }

IdempotencyResult IdempotencyStore::check_or_record(
    const OrderIntent& intent, ExecutionLedger& ledger, const ExecutionEvent& intent_received,
    const ExecutionEvent& conflict_incident) {
  const auto fingerprint = intent.semantic_fingerprint();
  const auto existing = intents_.find(intent.intent_id);
  if (existing != intents_.end()) {
    if (existing->second.semantic_fingerprint != fingerprint) {
      validate_conflict(intent, conflict_incident);
      static_cast<void>(ledger.append(conflict_incident));
      safety_stopped_ = true;
      return {IdempotencyOutcome::Conflict, existing->second.disposition,
              existing->second.internal_order_id};
    }
    if (existing->second.ambiguous) {
      return {IdempotencyOutcome::ReconciliationRequired, existing->second.disposition,
              existing->second.internal_order_id};
    }
    return {IdempotencyOutcome::Duplicate, existing->second.disposition,
            existing->second.internal_order_id};
  }
  if (safety_stopped_) return {IdempotencyOutcome::SafetyStopped, "safety_stop", std::nullopt};
  validate_received(intent, intent_received, fingerprint);
  const auto durable = ledger.append(intent_received);
  intents_.emplace(intent.intent_id,
                   IntentReplayState{fingerprint, durable.sequence, "received", std::nullopt,
                                     false, intent.strategy_id, intent.strategy_run_id,
                                     std::nullopt, std::nullopt});
  return {IdempotencyOutcome::NewIntent, "received", std::nullopt};
}

void IdempotencyStore::update(std::string_view intent_id, std::string disposition,
                              std::optional<std::string> internal_order_id, bool ambiguous) {
  const auto found = intents_.find(std::string(intent_id));
  if (found == intents_.end()) throw LedgerError("idempotency_unknown_intent");
  found->second.disposition = std::move(disposition);
  if (internal_order_id) found->second.internal_order_id = std::move(internal_order_id);
  found->second.ambiguous = ambiguous;
}
}  // namespace shaurya::execution
