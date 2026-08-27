#include "shaurya/execution/idempotency_store.hpp"
#include "shaurya/execution/ledger_replay.hpp"
#include "test_support.hpp"

#include <array>

using namespace shaurya::execution;
namespace {
OrderIntent intent(std::string id, std::uint64_t price = 25000) {
  return OrderIntent::parse(
      "{\"action\":\"place\",\"canonical_instrument_id\":\"NSE:NSE_FNO:NIFTY:option:"
      "2026-08-27:25000:CE\",\"created_at_ns\":100,\"execution_session_id\":"
      "\"00000000-0000-4000-8000-000000000003\",\"expires_at_ns\":200,\"intent_id\":\"" +
      id + "\",\"limit_price_paise\":" + std::to_string(price) +
      ",\"product\":\"NRML\",\"quantity\":65,\"schema_version\":\"1.0.0\","
      "\"side\":\"BUY\",\"strategy_id\":\"d51\",\"strategy_run_id\":"
      "\"00000000-0000-4000-8000-000000000002\",\"time_in_force\":\"DAY\"}");
}
ExecutionEvent received(const OrderIntent& value, std::string event_id) {
  return event(std::move(event_id), "intent_received",
               {{"semantic_fingerprint", JsonValue(value.semantic_fingerprint())}}, value.intent_id);
}
ExecutionEvent conflict(const OrderIntent& value, std::string event_id) {
  return event(std::move(event_id), "safety_stop",
               {{"reason", JsonValue(std::string("idempotency_conflict"))},
                {"error_code", JsonValue(std::string("IDEMPOTENCY_CONFLICT"))}}, value.intent_id);
}
}

int main() {
  const auto root = test_directory("idempotency");
  const auto path = root / "ledger.jsonl";
  const auto original = intent("00000000-0000-4000-8000-000000000001");
  const auto received_event = received(original, "00000000-0000-4000-8000-000000000101");
  const auto conflict_event = conflict(original, "00000000-0000-4000-8000-000000000102");
  IdempotencyStore store;
  {
    auto ledger = ExecutionLedger::create_new(path);
    const auto first = store.check_or_record(original, ledger, received_event, conflict_event);
    require_test(first.outcome == IdempotencyOutcome::NewIntent && ledger.last_sequence() == 1,
                 "new intent was not durably coupled");
    const auto duplicate = store.check_or_record(original, ledger, received_event, conflict_event);
    require_test(duplicate.outcome == IdempotencyOutcome::Duplicate && ledger.last_sequence() == 1,
                 "duplicate appended evidence");
    constexpr std::array dispositions{"mapped", "risk_approved", "submission_started",
        "acknowledged", "partially_filled", "filled", "cancelled", "rejected"};
    for (const auto disposition : dispositions) {
      store.update(original.intent_id, disposition);
      const auto replay = store.check_or_record(original, ledger, received_event, conflict_event);
      require_test(replay.outcome == IdempotencyOutcome::Duplicate &&
                       replay.disposition == disposition && ledger.last_sequence() == 1,
                   "pipeline duplicate was not side-effect free");
    }
    const auto changed = intent(original.intent_id, 25010);
    const auto blocked = store.check_or_record(changed, ledger, received_event, conflict_event);
    require_test(blocked.outcome == IdempotencyOutcome::Conflict && store.safety_stopped() &&
                     ledger.last_sequence() == 2,
                 "conflict did not durably safety-stop");
    const auto distinct = intent("00000000-0000-4000-8000-000000000009");
    const auto stopped = store.check_or_record(
        distinct, ledger, received(distinct, "00000000-0000-4000-8000-000000000109"),
        conflict(distinct, "00000000-0000-4000-8000-000000000110"));
    require_test(stopped.outcome == IdempotencyOutcome::SafetyStopped && ledger.last_sequence() == 2,
                 "new intent bypassed safety stop");
  }
  require_test(verify_ledger(path).verified_records == 2 && replay_ledger(path).safety_stopped,
               "conflict evidence missing after restart");

  ReconstructedState ambiguous_state;
  ambiguous_state.intents.emplace(
      original.intent_id,
      IntentReplayState{original.semantic_fingerprint(), 1, "ambiguous_submission",
                        std::optional<std::string>("00000000-0000-4000-8000-000000000201"), true});
  auto restarted = IdempotencyStore::from_reconstructed(ambiguous_state);
  const auto empty_path = root / "restart.jsonl";
  {
    auto ledger = ExecutionLedger::create_new(empty_path);
    const auto after_restart = restarted.check_or_record(original, ledger, received_event,
                                                          conflict_event);
    require_test(after_restart.outcome == IdempotencyOutcome::ReconciliationRequired &&
                     ledger.last_sequence() == 0,
                 "ambiguous restart retried intent");
  }

  const auto no_write_path = root / "no-write.jsonl";
  bool fail_before_write = true;
  IdempotencyStore no_write_store;
  {
    auto ledger = ExecutionLedger::create_new(no_write_path, [&](LedgerFaultPoint point) {
      if (fail_before_write && point == LedgerFaultPoint::BeforeWrite) throw std::runtime_error("x");
    });
    try {
      static_cast<void>(no_write_store.check_or_record(
          original, ledger, received_event, conflict_event));
      require_test(false, "injected no-write failure accepted");
    } catch (const LedgerError& error) {
      require_test(error.durability_boundary() == LedgerDurabilityBoundary::NotWritten,
                   "wrong no-write boundary");
    }
  }
  require_test(verify_ledger(no_write_path).verified_records == 0,
               "failed registration entered ledger");
  fail_before_write = false;
  {
    auto ledger = ExecutionLedger::open_existing(no_write_path);
    const auto retry = no_write_store.check_or_record(original, ledger, received_event,
                                                       conflict_event);
    require_test(retry.outcome == IdempotencyOutcome::NewIntent,
                 "non-durable registration polluted memory");
  }
  std::filesystem::remove_all(root);
}
