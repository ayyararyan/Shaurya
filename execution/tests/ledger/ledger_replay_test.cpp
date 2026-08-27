#include "shaurya/execution/ledger_replay.hpp"
#include "shaurya/execution/idempotency_store.hpp"
#include "test_support.hpp"

#include <array>

using namespace shaurya::execution;

namespace {
constexpr std::string_view kIntent = "00000000-0000-4000-8000-000000000001";
constexpr std::string_view kOrder = "00000000-0000-4000-8000-000000000201";
constexpr std::string_view kIntentTwo = "00000000-0000-4000-8000-000000000002";
constexpr std::string_view kOrderTwo = "00000000-0000-4000-8000-000000000202";
const std::string kInstrument = "NSE:NSE_FNO:NIFTY:option:2026-08-27:25000:CE";

JsonObject submission_payload() {
  return {{"canonical_instrument_id", JsonValue(kInstrument)},
          {"route_digest", JsonValue(std::string(64, 'b'))},
          {"side", JsonValue(std::string("BUY"))},
          {"quantity", JsonValue(JsonInteger{"65"})},
          {"limit_price_paise", JsonValue(JsonInteger{"25000"})}};
}
JsonObject mapping_payload() {
  return {{"routing_snapshot_digest", JsonValue(std::string(64, 'b'))},
          {"instrument_token", JsonValue(std::string("route-123"))},
          {"exchange_segment", JsonValue(std::string("nse_fo"))},
          {"trading_symbol", JsonValue(std::string("NIFTY26AUG25000CE"))},
          {"lot_size", JsonValue(JsonInteger{"65"})},
          {"tick_size_paise", JsonValue(JsonInteger{"5"})}};
}
JsonObject risk_payload(std::string_view intent_id) {
  RiskDecision decision;
  decision.decision_id = "00000000-0000-4000-8000-000000000301";
  decision.intent_id = std::string(intent_id);
  decision.decision = "approved";
  decision.timestamp_ns = 1000;
  decision.rule_set_version = "risk-v1";
  decision.configuration_digest = std::string(64, 'd');
  decision.rules_checked.push_back({"authority", "pass", 0, 0, 0, "state"});
  decision.mapping_age_ns = 0;
  decision.market_age_ns = 0;
  decision.session_state = "ready";
  return {{"broker_call_count", JsonValue(JsonInteger{"0"})},
          {"decision_id", JsonValue(decision.decision_id)},
          {"configuration_digest", JsonValue(decision.configuration_digest)},
          {"risk_decision", parse_json(decision.to_json())}};
}
JsonObject broker_payload(JsonObject payload, std::uint64_t sequence = 0U) {
  payload.emplace("source_sequence", JsonValue(JsonInteger{std::to_string(sequence)}));
  payload.emplace("source_fingerprint", JsonValue(std::string(64, 'f')));
  payload.emplace("source_provenance", JsonValue(std::string("simulated_proxy")));
  return payload;
}
}

int main() {
  const auto root = test_directory("replay");
  const auto path = root / "ledger.jsonl";
  {
    auto ledger = ExecutionLedger::create_new(path);
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000101", "intent_received",
        {{"semantic_fingerprint", JsonValue(std::string(64, 'a'))}}, std::string(kIntent))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000102", "mapping_validated", mapping_payload(),
        std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000103", "risk_approved", risk_payload(kIntent),
        std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000104", "submission_started",
        submission_payload(), std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000105", "broker_acknowledged",
        broker_payload({{"update_id", JsonValue(std::string("ack-1"))},
                        {"broker_order_id", JsonValue(std::string("paper-1"))}}),
        std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000106", "partially_filled",
        broker_payload({{"update_id", JsonValue(std::string("fill-1"))},
                        {"cumulative_filled_quantity", JsonValue(JsonInteger{"20"})}}, 1U),
        std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000117", "partially_filled",
        broker_payload({{"update_id", JsonValue(std::string("fill-2"))},
                        {"cumulative_filled_quantity", JsonValue(JsonInteger{"30"})}}, 2U),
        std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000107", "modify_requested",
        {{"update_id", JsonValue(std::string("modify-request-1"))},
         {"quantity", JsonValue(JsonInteger{"65"})},
         {"limit_price_paise", JsonValue(JsonInteger{"25005"})}},
        std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000108", "modified",
        broker_payload({{"update_id", JsonValue(std::string("modify-ack-1"))},
                        {"quantity", JsonValue(JsonInteger{"65"})},
                        {"limit_price_paise", JsonValue(JsonInteger{"25005"})}}),
        std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000109", "cancel_requested",
        {{"update_id", JsonValue(std::string("cancel-request-1"))}},
        std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000110", "cancelled",
        broker_payload({{"update_id", JsonValue(std::string("cancel-ack-1"))}}),
        std::string(kIntent), std::string(kOrder))));
  }
  const auto state = replay_ledger(path);
  const auto repeated = replay_ledger(path);
  require_test(state.intents.size() == 1 && state.orders.size() == 1, "replay identity");
  require_test(state.positions.at(kInstrument) == 30, "position");
  require_test(state.route_positions.at("route-123") == 30, "route-token position");
  require_test(state.orders.begin()->second.cumulative_filled_quantity == 30, "fill");
  require_test(state.last_broker_update_sequence == 2U &&
                   state.broker_update_fingerprints.contains("fill-1") &&
                   state.broker_update_fingerprints.contains("fill-2"),
               "broker update sequence/fingerprint did not survive restart replay");
  require_test(state.broker_attempt_timestamps_ns ==
                   std::vector<std::int64_t>({100, 100}),
               "durable place/modify attempt timestamps did not survive replay");
  require_test(state.orders.begin()->second.limit_price_paise == 25005 &&
                   state.orders.begin()->second.state == OrderState::Cancelled,
               "modify/cancel replay");
  require_test(repeated.positions == state.positions &&
                   repeated.orders.at(std::string(kOrder)) == state.orders.at(std::string(kOrder)),
               "replay not deterministic");

  const auto ambiguous_path = root / "ambiguous.jsonl";
  {
    auto ledger = ExecutionLedger::create_new(ambiguous_path);
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000111", "intent_received",
        {{"semantic_fingerprint", JsonValue(std::string(64, 'c'))}}, std::string(kIntent))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000112", "mapping_validated", mapping_payload(),
        std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000113", "risk_approved", risk_payload(kIntent),
        std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000114", "submission_started",
        submission_payload(), std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000115", "ambiguous_submission",
        broker_payload({{"error_code", JsonValue(std::string("broker_outcome_uncertain"))},
                        {"update_id", JsonValue(std::string("ambiguous-1"))}}),
        std::string(kIntent), std::string(kOrder))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000121", "intent_received",
        {{"semantic_fingerprint", JsonValue(std::string(64, 'e'))}}, std::string(kIntentTwo))));
    auto second_mapping = mapping_payload();
    second_mapping["instrument_token"] = JsonValue(std::string("route-456"));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000122", "mapping_validated", second_mapping,
        std::string(kIntentTwo), std::string(kOrderTwo))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000123", "risk_approved", risk_payload(kIntentTwo),
        std::string(kIntentTwo), std::string(kOrderTwo))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000124", "submission_started",
        submission_payload(), std::string(kIntentTwo), std::string(kOrderTwo))));
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000125", "ambiguous_submission",
        broker_payload({{"error_code", JsonValue(std::string("broker_outcome_uncertain"))},
                        {"update_id", JsonValue(std::string("ambiguous-2"))}}),
        std::string(kIntentTwo), std::string(kOrderTwo))));
  }
  auto ambiguous = replay_ledger(ambiguous_path);
  require_test(ambiguous.reconciliation_required && ambiguous.intents.at(std::string(kIntent)).ambiguous,
               "ambiguity did not survive replay");
  const auto restarted = IdempotencyStore::from_reconstructed(ambiguous);
  static_cast<void>(restarted);

  {
    auto ledger = ExecutionLedger::open_existing(ambiguous_path);
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000116", "reconciliation_completed",
        {{"authoritative_state", JsonValue(std::string("working"))},
         {"update_id", JsonValue(std::string("reconcile-1"))},
         {"broker_order_id", JsonValue(std::string("paper-2"))},
         {"cumulative_filled_quantity", JsonValue(JsonInteger{"5"})}},
        std::string(kIntent), std::string(kOrder))));
  }
  const auto one_reconciled = replay_ledger(ambiguous_path);
  require_test(one_reconciled.reconciliation_required &&
                   !one_reconciled.intents.at(std::string(kIntent)).ambiguous &&
                   one_reconciled.intents.at(std::string(kIntentTwo)).ambiguous,
               "one reconciliation cleared another ambiguity");
  {
    auto ledger = ExecutionLedger::open_existing(ambiguous_path);
    static_cast<void>(ledger.append(event(
        "00000000-0000-4000-8000-000000000126", "reconciliation_completed",
        {{"authoritative_state", JsonValue(std::string("working"))},
         {"update_id", JsonValue(std::string("reconcile-2"))},
         {"broker_order_id", JsonValue(std::string("paper-3"))},
         {"cumulative_filled_quantity", JsonValue(JsonInteger{"5"})}},
        std::string(kIntentTwo), std::string(kOrderTwo))));
  }
  const auto reconciled = replay_ledger(ambiguous_path);
  require_test(!reconciled.reconciliation_required && reconciled.positions.at(kInstrument) == 10 &&
                   reconciled.route_positions.at("route-123") == 5 &&
                   reconciled.route_positions.at("route-456") == 5 &&
                   reconciled.orders.at(std::string(kOrder)).state == OrderState::PartiallyFilled,
               "authoritative reconciliation not replayed");

  const std::array crash_events{
      event("00000000-0000-4000-8000-000000000141", "intent_received",
            {{"semantic_fingerprint", JsonValue(std::string(64, 'a'))}}, std::string(kIntent)),
      event("00000000-0000-4000-8000-000000000142", "mapping_validated", mapping_payload(),
            std::string(kIntent), std::string(kOrder)),
      event("00000000-0000-4000-8000-000000000143", "risk_approved", risk_payload(kIntent),
            std::string(kIntent), std::string(kOrder)),
      event("00000000-0000-4000-8000-000000000144", "submission_started",
            submission_payload(), std::string(kIntent), std::string(kOrder)),
      event("00000000-0000-4000-8000-000000000145", "broker_acknowledged",
            broker_payload({{"update_id", JsonValue(std::string("crash-ack"))},
                            {"broker_order_id", JsonValue(std::string("paper-crash"))}}),
            std::string(kIntent), std::string(kOrder)),
      event("00000000-0000-4000-8000-000000000146", "partially_filled",
            broker_payload({{"update_id", JsonValue(std::string("crash-fill"))},
                            {"cumulative_filled_quantity", JsonValue(JsonInteger{"20"})}}, 1U),
            std::string(kIntent), std::string(kOrder))};
  for (std::size_t cut = 1; cut <= crash_events.size(); ++cut) {
    const auto crash_path = root / ("crash-cut-" + std::to_string(cut) + ".jsonl");
    {
      auto ledger = ExecutionLedger::create_new(crash_path);
      for (std::size_t index = 0; index < cut; ++index) {
        static_cast<void>(ledger.append(crash_events[index]));
      }
    }
    const auto recovered = replay_ledger(crash_path);
    require_test(recovered.intents.size() == 1, "crash replay lost intent");
    if (cut < 4) require_test(recovered.orders.empty(), "pre-submission crash created order");
    if (cut >= 4) require_test(recovered.orders.size() == 1, "post-submission crash lost order");
    if (cut == 6) require_test(recovered.positions.at(kInstrument) == 20,
                               "post-fill crash lost position");
  }

  std::filesystem::remove_all(root);
}
