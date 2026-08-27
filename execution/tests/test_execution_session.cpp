#include "shaurya/execution/execution_session.hpp"
#include "shaurya/execution/paper_broker.hpp"

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <iostream>
#include <set>
#include <thread>
#include <unistd.h>

using namespace shaurya::execution;

namespace {
struct Clock final : SessionClock {
  std::int64_t value{1000};
  mutable unsigned overflow_after_calls{std::numeric_limits<unsigned>::max()};
  std::int64_t now_ns() const noexcept override {
    if (overflow_after_calls == 0U) {
      overflow_after_calls = std::numeric_limits<unsigned>::max();
      return std::numeric_limits<std::int64_t>::max();
    }
    if (overflow_after_calls != std::numeric_limits<unsigned>::max()) --overflow_after_calls;
    return value;
  }
};
struct Ledger final : SessionLedger {
  std::vector<SessionAuditRecord> records; std::string fail_kind;
  unsigned failures_remaining{std::numeric_limits<unsigned>::max()};
  std::optional<ReconstructedState> replay_state;
  LedgerDurabilityBoundary fail_boundary{LedgerDurabilityBoundary::NotWritten};
  bool append(const SessionAuditRecord& record) override {
    if (record.kind == fail_kind && failures_remaining != 0U) {
      --failures_remaining; return false;
    }
    records.push_back(record); return true;
  }
  LedgerDurabilityBoundary append_event(const ExecutionEvent& event) override {
    if (event.event_type == fail_kind && failures_remaining != 0U) {
      --failures_remaining; return fail_boundary;
    }
    return SessionLedger::append_event(event);
  }
  bool flush() override { return true; }
  std::optional<ReconstructedState> reconstructed_state() const override {
    return replay_state;
  }
};
struct Resolver final : SessionRoutingResolver {
  RoutingRecord route{"NSE:NSE_FNO:NIFTY:future:2026-08-27", "58072", "nse_fo",
                      "NIFTY26AUGFUT", 65, 5};
  RoutingRecord bank_route{"NSE:NSE_FNO:BANKNIFTY:future:2026-08-27", "58073", "nse_fo",
                           "BANKNIFTY26AUGFUT", 15, 5};
  ResolutionResult resolve(std::string_view canonical) const override {
    if (throwing.erase(std::string(canonical)) != 0U)
      throw std::runtime_error("fixture_resolution_failure");
    if (missing.contains(std::string(canonical)))
      return {std::nullopt, RoutingErrorCode::NotFound};
    if (canonical == route.canonical_instrument_id) return {route, std::nullopt};
    if (canonical == bank_route.canonical_instrument_id) return {bank_route, std::nullopt};
    return {std::nullopt, RoutingErrorCode::NotFound};
  }
  std::string_view snapshot_digest() const noexcept override { return digest; }
  bool valid_for_trading_date(std::string_view date) const noexcept override { return date == "2026-08-27"; }
  std::optional<std::int64_t> mapping_timestamp_ns() const noexcept override { return 950; }
  std::string digest = std::string(64, 'd');
  std::set<std::string> missing;
  mutable std::set<std::string> throwing;
};
struct Broker final : BrokerAdapter {
  unsigned mutations{}; mutable BrokerSessionHealth health{BrokerSessionHealth::Ready};
  mutable unsigned lost_health_queries{};
  bool throw_mutation{}; bool ambiguous_mutation{};
  std::vector<BrokerOrderSnapshot> orders;
  std::vector<BrokerPositionSnapshot> positions;
  std::vector<BrokerFillSnapshot> observation_fills;
  mutable unsigned position_query_failures{};
  mutable unsigned unavailable_pnl_queries{};
  mutable unsigned order_query_calls{};
  mutable unsigned trade_query_calls{};
  mutable unsigned position_query_calls{};
  unsigned transition_on_order_query{};
  unsigned transition_on_trade_query{};
  unsigned transition_on_position_query{};
  BrokerSessionHealth transition_health{BrokerSessionHealth::Ready};
  bool shutdown_operations_bounded_nonblocking() const noexcept override { return true; }
  BrokerMutationResult place(const BrokerOrderRequest& request) override {
    ++mutations;
    if (throw_mutation) throw std::runtime_error("fixture_timeout");
    if (ambiguous_mutation)
      return {BrokerMutationStatus::Ambiguous, request.internal_order_id, std::nullopt,
              "simulated_proxy", BrokerError{"timeout", std::nullopt, "timeout-1"}};
    orders.push_back({request.internal_order_id, request.route.canonical_instrument_id,
                      request.route.instrument_token, request.side, request.quantity,
                      request.limit_price_paise, 0, "working", "simulated_proxy"});
    return {BrokerMutationStatus::Acknowledged, request.internal_order_id, "paper-1",
            "simulated_proxy", std::nullopt};
  }
  BrokerMutationResult modify(const BrokerModifyRequest& request) override {
    ++mutations;
    for (auto& order : orders) if (order.internal_order_id == request.internal_order_id) {
      order.quantity = request.quantity; order.limit_price_paise = request.limit_price_paise;
    }
    return {BrokerMutationStatus::Acknowledged, request.internal_order_id,
                         "paper-2", "simulated_proxy", std::nullopt, false,
                         request.quantity, request.limit_price_paise};
  }
  BrokerMutationResult cancel(std::string_view id) override {
    ++mutations;
    for (auto& order : orders) if (order.internal_order_id == id) order.state = "cancelled";
    return {BrokerMutationStatus::Acknowledged, std::string(id), "paper-3",
            "simulated_proxy", std::nullopt, true};
  }
  BrokerQueryResult<BrokerOrderSnapshot> query_orders() const override {
    ++order_query_calls;
    if (transition_on_order_query != 0U && order_query_calls == transition_on_order_query)
      health = transition_health;
    return {BrokerQueryStatus::Authoritative, orders, "simulated_proxy"};
  }
  BrokerQueryResult<BrokerFillSnapshot> query_trades() const override {
    ++trade_query_calls;
    if (transition_on_trade_query != 0U && trade_query_calls == transition_on_trade_query)
      health = transition_health;
    return {BrokerQueryStatus::Authoritative, {}, "simulated_proxy"};
  }
  BrokerQueryResult<BrokerPositionSnapshot> query_positions() const override {
    ++position_query_calls;
    if (transition_on_position_query != 0U &&
        position_query_calls == transition_on_position_query)
      health = transition_health;
    if (position_query_failures != 0U) {
      --position_query_failures;
      throw std::runtime_error("fixture_position_query_failure");
    }
    return {BrokerQueryStatus::Authoritative, positions, "simulated_proxy"};
  }
  BrokerPnlSnapshot query_pnl() const override {
    if (unavailable_pnl_queries != 0U) {
      --unavailable_pnl_queries;
      return {BrokerQueryStatus::Unavailable, 950, 0, 0, "paper", "simulated_proxy"};
    }
    return {BrokerQueryStatus::Authoritative, 950, 0, 0, "paper", "simulated_proxy"};
  }
  std::vector<BrokerFillSnapshot> accept_observation(
      const MarketObservation&) override {
    auto result = observation_fills;
    observation_fills.clear();
    return result;
  }
  BrokerSessionHealth session_health() const noexcept override {
    if (lost_health_queries != 0U) {
      --lost_health_queries; return BrokerSessionHealth::Lost;
    }
    return health;
  }
};
struct BlockingBroker final : BrokerAdapter {
  mutable unsigned calls{};
  void block() const { ++calls; std::this_thread::sleep_for(std::chrono::milliseconds(250)); }
  BrokerMutationResult place(const BrokerOrderRequest& request) override {
    block(); return {BrokerMutationStatus::Ambiguous, request.internal_order_id, std::nullopt,
                     "proxy", std::nullopt};
  }
  BrokerMutationResult modify(const BrokerModifyRequest& request) override {
    block(); return {BrokerMutationStatus::Ambiguous, request.internal_order_id, std::nullopt,
                     "proxy", std::nullopt};
  }
  BrokerMutationResult cancel(std::string_view id) override {
    block(); return {BrokerMutationStatus::Ambiguous, std::string(id), std::nullopt,
                     "proxy", std::nullopt};
  }
  BrokerQueryResult<BrokerOrderSnapshot> query_orders() const override { block(); return {}; }
  BrokerQueryResult<BrokerFillSnapshot> query_trades() const override { block(); return {}; }
  BrokerQueryResult<BrokerPositionSnapshot> query_positions() const override { block(); return {}; }
  BrokerSessionHealth session_health() const noexcept override { return BrokerSessionHealth::Unknown; }
};
struct Coordinator final : SessionStageCoordinator {
  std::vector<bool> broker_attempted;
  unsigned pre_attempt_refusals{};
  unsigned pre_attempt_exceptions{};
  unsigned risk_evaluation_exceptions{};
  bool acknowledge_ledger_boundary(std::uint64_t, bool attempted) override {
    broker_attempted.push_back(attempted);
    if (!attempted && pre_attempt_exceptions != 0U) {
      --pre_attempt_exceptions;
      throw std::runtime_error("fixture_coordinator_failure");
    }
    if (!attempted && pre_attempt_refusals != 0U) {
      --pre_attempt_refusals; return false;
    }
    return true;
  }
  bool reserve_broker_updates(std::size_t) override { return true; }
  bool dispatch_broker_update(BrokerUpdateEnvelope) override { return true; }
  void release_broker_update_reservations() noexcept override {}
  void before_shutdown_risk_evaluation() override {
    if (risk_evaluation_exceptions != 0U) {
      --risk_evaluation_exceptions;
      throw std::runtime_error("fixture_risk_evaluation_failure");
    }
  }
};
RiskConfiguration config() {
  RiskConfiguration value;
  value.configuration_version = "risk-v1"; value.trading_date = "2026-08-27";
  value.maximum_observation_age_ns = 100; value.maximum_mapping_age_ns = 100;
  value.maximum_greek_age_ns = 100; value.maximum_clock_skew_ns = 5;
  value.maximum_order_quantity = 130; value.maximum_absolute_instrument_position = 260;
  value.maximum_gross_premium_paise = 1000000000; value.maximum_outstanding_orders = 4;
  value.maximum_orders_per_window = 4; value.order_rate_window_ns = 1000;
  value.maximum_daily_loss_paise = 100000; value.maximum_drawdown_paise = 50000;
  value.configuration_digest = sha256_hex(value.canonical_payload()); return value;
}
OrderIntent intent() {
  OrderIntent value;
  value.intent_id = "00000000-0000-4000-8000-000000000001";
  value.strategy_id = "d51";
  value.strategy_run_id = "00000000-0000-4000-8000-000000000002";
  value.execution_session_id = "00000000-0000-4000-8000-000000000003";
  value.created_at_ns = 900; value.expires_at_ns = 2000;
  value.canonical_instrument_id = "NSE:NSE_FNO:NIFTY:future:2026-08-27";
  value.action = IntentAction::Place; value.side = OrderSide::Buy; value.quantity = 65;
  value.limit_price_paise = 1000; value.product = "NRML"; value.time_in_force = "DAY";
  return value;
}
MarketObservation observation() {
  MarketObservation value; value.canonical_instrument_id = intent().canonical_instrument_id;
  value.best_bid_paise = 995; value.best_ask_paise = 1000; value.cumulative_volume = 10;
  value.receive_timestamp_ns = 950; value.source = "dhan"; value.provenance = "observed";
  return value;
}
SessionLaunchEvidence launch_evidence() {
  return {std::string(64U, 'f'), "00000000-0000-4000-8000-000000000004",
          "00000000-0000-4000-8000-000000000003", "operator-1", "device-1",
          "SHA256:fingerprint", std::string(64U, 'a'), std::string(64U, 'b'),
          std::string(64U, 'c'), "shadow", "SHAURYA_SHADOW_LAUNCH", 900};
}
}

int main() {
  int failures = 0;
  const auto expect = [&](bool condition, const char* message) {
    if (!condition) { std::cerr << message << '\n'; ++failures; }
  };
  Clock clock; Resolver resolver; Broker broker; Ledger ledger;
  Broker launch_broker; Ledger launch_ledger;
  ExecutionSession launched("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                            launch_ledger, resolver, launch_broker, clock, 1024U,
                            launch_evidence());
  expect(launched.start(), "launch-evidence session did not reconcile");
  expect(!launched.ready(), "launch-evidence session became ready before observation");
  launched.accept_observation(observation());
  expect(launched.ready(), "launch-evidence session did not activate after observation");
  const auto launch_record = std::find_if(
      launch_ledger.records.begin(), launch_ledger.records.end(),
      [](const SessionAuditRecord& record) { return record.kind == "session_started"; });
  expect(launch_record != launch_ledger.records.end() &&
             ExecutionEvent::parse(launch_record->event.to_json()) == launch_record->event &&
             json_string(launch_record->event.payload.at("launch_attestation_digest"),
                         "launch_attestation_digest") == std::string(64U, 'f') &&
             json_string(launch_record->event.payload.at("invocation_id"), "invocation_id") ==
                 launch_evidence().invocation_id,
         "session launch evidence was not durably round-tripped unchanged");
  if (launch_record != launch_ledger.records.end()) {
    auto partial = launch_record->event;
    partial.payload.erase("device_id");
    bool rejected_partial = false;
    try { (void)ExecutionEvent::parse(partial.to_json()); }
    catch (const JsonError&) { rejected_partial = true; }
    expect(rejected_partial, "partial launch-evidence group accepted");
  }
  ExecutionSession session("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                           ledger, resolver, broker, clock);
  expect(session.start(), "session did not reconcile");
  session.accept_observation(observation());
  const auto accepted = session.accept_intent(intent());
  expect(risk_approved(accepted.decision) && broker.mutations == 1U, "accepted intent not submitted once");
  const auto duplicate = session.accept_intent(intent());
  expect(duplicate.replayed_duplicate && duplicate.broker_result && broker.mutations == 1U,
         "duplicate resubmitted");
  const std::vector<std::string> expected = {"intent_received", "mapping_validated", "risk_approved",
                                             "submission_started", "broker_acknowledged"};
  std::size_t cursor = 0;
  for (const auto& record : ledger.records)
    if (cursor < expected.size() && record.kind == expected[cursor]) ++cursor;
  expect(cursor == expected.size(), "durable mutation sequence violated");
  const auto risk_record = std::find_if(
      ledger.records.begin(), ledger.records.end(),
      [](const SessionAuditRecord& record) { return record.kind == "risk_approved"; });
  expect(risk_record != ledger.records.end() &&
             json_uint64(risk_record->event.payload.at("broker_call_count"),
                         "broker_call_count") == 0U &&
             RiskDecision::parse(canonical_json(
                 risk_record->event.payload.at("risk_decision"))) == accepted.decision,
         "full immutable pre-broker RiskDecision evidence was not durable");

  Broker two_fill_broker; Ledger two_fill_ledger;
  ExecutionSession two_fill("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                            two_fill_ledger, resolver, two_fill_broker, clock);
  expect(two_fill.start(), "two-fill fixture startup");
  two_fill.accept_observation(observation());
  const auto first_two_fill = two_fill.accept_intent(intent());
  auto second_intent = intent();
  second_intent.intent_id = "00000000-0000-4000-8000-000000000090";
  const auto second_two_fill = two_fill.accept_intent(second_intent);
  const auto first_two_fill_id = first_two_fill.broker_result->internal_order_id;
  const auto second_two_fill_id = second_two_fill.broker_result->internal_order_id;
  two_fill_broker.observation_fills = {
      {"two-fill-1", first_two_fill_id, intent().canonical_instrument_id, "58072",
       65, 65, 1000, 951, "simulated_proxy"},
      {"two-fill-2", second_two_fill_id, intent().canonical_instrument_id, "58072",
       65, 65, 1000, 951, "simulated_proxy"}};
  auto fill_observation = observation(); fill_observation.receive_timestamp_ns = 951;
  two_fill.accept_observation(fill_observation);
  std::vector<std::uint64_t> fill_sequences;
  for (const auto& record : two_fill_ledger.records) {
    if (record.kind == "filled")
      fill_sequences.push_back(json_uint64(record.event.payload.at("source_sequence"),
                                           "source_sequence"));
  }
  expect(fill_sequences == std::vector<std::uint64_t>({1U, 2U}) && !two_fill.safety_stopped(),
         "two fills from one observation reused a broker-update sequence");
  const auto placed_order_id = broker.orders.front().internal_order_id;
  auto modify_intent = intent();
  modify_intent.intent_id = "00000000-0000-4000-8000-000000000010";
  modify_intent.action = IntentAction::Modify;
  modify_intent.target_internal_order_id = placed_order_id;
  modify_intent.limit_price_paise = 1005;
  const auto modified = session.accept_intent(modify_intent);
  expect(risk_approved(modified.decision) && modified.broker_result &&
             broker.orders.front().limit_price_paise == 1005,
         "valid modify not bound/applied");
  auto cancel_intent = intent();
  cancel_intent.intent_id = "00000000-0000-4000-8000-000000000011";
  cancel_intent.action = IntentAction::Cancel;
  cancel_intent.side.reset();
  cancel_intent.quantity.reset();
  cancel_intent.limit_price_paise.reset();
  cancel_intent.product.reset();
  cancel_intent.time_in_force.reset();
  cancel_intent.target_internal_order_id = placed_order_id;
  const auto cancelled = session.accept_intent(cancel_intent);
  expect(risk_approved(cancelled.decision) && cancelled.broker_result &&
             broker.orders.front().state == "cancelled",
         "valid cancel not confirmed through FSM");
  BrokerUpdateEnvelope foreign_update;
  foreign_update.sequence = 1;
  foreign_update.update_id = "foreign-update-1";
  foreign_update.strategy_id = "other_strategy";
  foreign_update.strategy_run_id = intent().strategy_run_id;
  foreign_update.intent_id = intent().intent_id;
  foreign_update.internal_order_id = placed_order_id;
  foreign_update.kind = OrderEventKind::FillUpdate;
  foreign_update.cumulative_filled_quantity = 65;
  expect(!session.accept_broker_update(foreign_update) && session.safety_stopped(),
         "foreign broker-update correlation accepted");

  Broker blocked_broker; Ledger blocked_ledger; blocked_ledger.fail_kind = "submission_started";
  ExecutionSession blocked("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                           blocked_ledger, resolver, blocked_broker, clock);
  expect(blocked.start(), "blocked fixture startup"); blocked.accept_observation(observation());
  const auto blocked_result = blocked.accept_intent(intent());
  expect(!blocked_result.broker_result && blocked_broker.mutations == 0U && blocked.safety_stopped(),
         "ledger failure called broker");

  Broker uncertain_broker; Ledger uncertain_ledger;
  uncertain_ledger.fail_kind = "broker_acknowledged";
  uncertain_ledger.fail_boundary = LedgerDurabilityBoundary::Uncertain;
  ExecutionSession uncertain("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                             uncertain_ledger, resolver, uncertain_broker, clock);
  expect(uncertain.start(), "uncertain fixture startup");
  uncertain.accept_observation(observation());
  const auto uncertain_result = uncertain.accept_intent(intent());
  expect(uncertain_result.broker_result && uncertain_broker.mutations == 1U &&
             uncertain.safety_stopped() && uncertain.reconciliation_required(),
         "post-attempt uncertain durability did not stop");
  static_cast<void>(uncertain.accept_intent(intent()));
  expect(uncertain_broker.mutations == 1U, "uncertain durable boundary retried broker");

  Broker killed_broker; Ledger killed_ledger;
  ExecutionSession killed("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                          killed_ledger, resolver, killed_broker, clock);
  expect(killed.start(), "kill fixture startup"); killed.accept_observation(observation());
  killed.activate_kill_switch("operator_test");
  const auto rejected = killed.accept_intent(intent());
  expect(!risk_approved(rejected.decision) && killed_broker.mutations == 0U,
         "risk rejection mutated broker");

  Broker reduction_broker; Ledger reduction_ledger;
  ExecutionSession reduction("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                             reduction_ledger, resolver, reduction_broker, clock);
  expect(reduction.start(), "reduction fixture startup");
  reduction.accept_observation(observation());
  static_cast<void>(reduction.accept_intent(intent()));
  const auto reduction_order_id = reduction_broker.orders.front().internal_order_id;
  reduction.activate_kill_switch("operator_test");
  auto stopped_modify = intent();
  stopped_modify.intent_id = "00000000-0000-4000-8000-000000000081";
  stopped_modify.action = IntentAction::Modify;
  stopped_modify.target_internal_order_id = reduction_order_id;
  expect(!risk_approved(reduction.accept_intent(stopped_modify).decision) &&
             reduction_broker.mutations == 1U,
         "modify was permitted after SafetyStopped");
  auto reducing_cancel = intent();
  reducing_cancel.intent_id = "00000000-0000-4000-8000-000000000082";
  reducing_cancel.action = IntentAction::Cancel;
  reducing_cancel.side.reset(); reducing_cancel.quantity.reset();
  reducing_cancel.limit_price_paise.reset(); reducing_cancel.product.reset();
  reducing_cancel.time_in_force.reset();
  reducing_cancel.target_internal_order_id = reduction_order_id;
  const auto reduced = reduction.accept_intent(reducing_cancel);
  expect(risk_approved(reduced.decision) && reduced.broker_result &&
             reduction_broker.mutations == 2U,
         "risk-reducing cancel was blocked after SafetyStopped");

  Broker phased_broker; Ledger phased_ledger;
  ExecutionSession phased("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                          phased_ledger, resolver, phased_broker, clock);
  expect(phased.start(), "phased fixture startup"); phased.accept_observation(observation());
  auto prepared = phased.prepare_intent(intent());
  auto moved_prepared = std::move(prepared);
  bool moved_from_rejected = false;
  try { static_cast<void>(phased.submit_prepared(std::move(prepared))); }
  catch (const std::invalid_argument&) { moved_from_rejected = true; }
  expect(moved_from_rejected && phased_broker.mutations == 0U,
         "moved-from prepared token remained broker-capable");
  phased.activate_kill_switch("interleaving_test");
  const auto stale_prepared = phased.submit_prepared(std::move(moved_prepared));
  expect(!stale_prepared.broker_result && phased_broker.mutations == 0U,
         "stale prepared authority crossed the broker boundary");

  Broker wrong_owner_broker; Ledger wrong_owner_ledger;
  ExecutionSession wrong_owner("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                               wrong_owner_ledger, resolver, wrong_owner_broker, clock);
  expect(wrong_owner.start(), "wrong-owner fixture startup");
  wrong_owner.accept_observation(observation());
  auto foreign_prepared = wrong_owner.prepare_intent(intent());
  bool wrong_session_rejected = false;
  try { static_cast<void>(session.submit_prepared(std::move(foreign_prepared))); }
  catch (const std::invalid_argument&) { wrong_session_rejected = true; }
  expect(wrong_session_rejected && wrong_owner_broker.mutations == 0U,
         "prepared token was accepted by a different session instance");

  Broker single_use_broker; Ledger single_use_ledger;
  ExecutionSession single_use("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                              single_use_ledger, resolver, single_use_broker, clock);
  expect(single_use.start(), "single-use fixture startup");
  single_use.accept_observation(observation());
  auto single_use_token = single_use.prepare_intent(intent());
  static_cast<void>(single_use.submit_prepared(std::move(single_use_token)));
  bool double_submit_rejected = false;
  try { static_cast<void>(single_use.submit_prepared(std::move(single_use_token))); }
  catch (const std::invalid_argument&) { double_submit_rejected = true; }
  expect(double_submit_rejected && single_use_broker.mutations == 1U,
         "prepared token performed more than one broker mutation");

  Broker throwing_broker; throwing_broker.throw_mutation = true; Ledger throwing_ledger;
  ExecutionSession throwing("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                            throwing_ledger, resolver, throwing_broker, clock);
  expect(throwing.start(), "throw fixture startup"); throwing.accept_observation(observation());
  const auto thrown = throwing.accept_intent(intent());
  expect(thrown.broker_result &&
             thrown.broker_result->status == BrokerMutationStatus::Ambiguous &&
             throwing.safety_stopped() && throwing.reconciliation_required() &&
             throwing_broker.mutations == 1U,
         "broker exception was not durably ambiguous");
  const auto thrown_duplicate = throwing.accept_intent(intent());
  expect(thrown_duplicate.replayed_duplicate && throwing_broker.mutations == 1U,
         "ambiguous exception retried broker");

  Broker foreign_broker; Ledger foreign_ledger;
  ExecutionSession foreign("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                           foreign_ledger, resolver, foreign_broker, clock);
  expect(foreign.start(), "foreign fixture startup"); foreign.accept_observation(observation());
  auto foreign_intent = intent();
  foreign_intent.execution_session_id = "00000000-0000-4000-8000-000000000099";
  const auto foreign_result = foreign.accept_intent(foreign_intent);
  expect(foreign_result.decision.rejection_code == "intent_correlation_mismatch" &&
             foreign_broker.mutations == 0U, "cross-session intent reached broker");
  auto valid_after_foreign = intent();
  valid_after_foreign.intent_id = "00000000-0000-4000-8000-000000000098";
  const auto valid_after_foreign_result = foreign.accept_intent(valid_after_foreign);
  expect(risk_approved(valid_after_foreign_result.decision) && foreign_broker.mutations == 1U,
         "rejected foreign session poisoned strategy/run binding");

  Broker marked_broker; Ledger marked_ledger;
  ExecutionSession marked("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                          marked_ledger, resolver, marked_broker, clock);
  expect(marked.start(), "multi-mark fixture startup");
  marked.accept_observation(observation());
  auto second_observation = observation();
  second_observation.canonical_instrument_id =
      "NSE:NSE_FNO:BANKNIFTY:future:2026-08-27";
  second_observation.best_bid_paise = 1995;
  second_observation.best_ask_paise = 2000;
  second_observation.last_trade_paise = 1500;
  auto first_conservative_observation = observation();
  first_conservative_observation.last_trade_paise = 900;
  marked.accept_observation(first_conservative_observation);
  marked.accept_observation(second_observation);
  marked_broker.positions = {
      {intent().canonical_instrument_id, "58072", 10, "simulated_proxy"},
      {second_observation.canonical_instrument_id, "58073", 20, "simulated_proxy"}};
  auto marked_intent = intent();
  marked_intent.intent_id = "00000000-0000-4000-8000-000000000097";
  const auto marked_result = marked.accept_intent(marked_intent);
  const auto gross_rule = std::find_if(
      marked_result.decision.rules_checked.begin(), marked_result.decision.rules_checked.end(),
      [](const RuleCheck& rule) { return rule.rule == "gross_premium"; });
  expect(gross_rule != marked_result.decision.rules_checked.end() &&
             gross_rule->before_value == 50000 && gross_rule->projected_value == 115000,
         "multi-instrument positions were not marked by their own observations");

  Broker swapped_route_broker; Ledger swapped_route_ledger;
  ExecutionSession swapped_route(
      "00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
      swapped_route_ledger, resolver, swapped_route_broker, clock);
  expect(swapped_route.start(), "swapped-route fixture startup");
  swapped_route.accept_observation(observation());
  swapped_route_broker.positions = {
      {intent().canonical_instrument_id, "58073", 65, "simulated_proxy"}};
  auto swapped_sell = intent();
  swapped_sell.intent_id = "00000000-0000-4000-8000-000000000095";
  swapped_sell.side = OrderSide::Sell;
  expect(!risk_approved(swapped_route.accept_intent(swapped_sell).decision) &&
             swapped_route_broker.mutations == 0U,
         "runtime position with a swapped route token entered SELL authority");

  Broker invalid_order_broker; Ledger invalid_order_ledger;
  ExecutionSession invalid_order(
      "00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
      invalid_order_ledger, resolver, invalid_order_broker, clock);
  expect(invalid_order.start(), "invalid-order fixture startup");
  invalid_order.accept_observation(observation());
  invalid_order_broker.orders = {{
      "00000000-0000-4000-8000-000000000094", intent().canonical_instrument_id,
      "58072", OrderSide::Buy, 0, 0, 0, "working", "simulated_proxy"}};
  auto after_invalid_order = intent();
  after_invalid_order.intent_id = "00000000-0000-4000-8000-000000000093";
  expect(!risk_approved(invalid_order.accept_intent(after_invalid_order).decision) &&
             invalid_order_broker.mutations == 0U,
         "zero-quantity/zero-price runtime order entered risk calculations");
  invalid_order_broker.orders.front().quantity = 65;
  invalid_order_broker.orders.front().limit_price_paise = 1000;
  invalid_order_broker.orders.front().state = "unknown_working_shape";
  auto after_unknown_state = intent();
  after_unknown_state.intent_id = "00000000-0000-4000-8000-000000000091";
  expect(!risk_approved(invalid_order.accept_intent(after_unknown_state).decision) &&
             invalid_order_broker.mutations == 0U,
         "unknown runtime order state entered working-order authority");

  Broker queue_broker; Ledger queue_ledger;
  ExecutionSession queued("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                          queue_ledger, resolver, queue_broker, clock, 1);
  expect(queued.start(), "queue fixture startup");
  BrokerUpdateEnvelope update; update.sequence = 1; update.update_id = "update-1";
  BrokerUpdateEnvelope update2; update2.sequence = 2; update2.update_id = "update-2";
  expect(queued.enqueue_broker_update(update) && !queued.enqueue_broker_update(update2) &&
             queued.safety_stopped(),
         "real queue overflow did not stop");

  Broker restart_broker; Ledger restart_ledger;
  const std::string restart_order_id = "00000000-0000-4000-8000-000000000089";
  const std::string restart_modify_intent = "00000000-0000-4000-8000-000000000088";
  OrderAggregate restart_order;
  restart_order.internal_order_id = restart_order_id;
  restart_order.canonical_instrument_id = intent().canonical_instrument_id;
  restart_order.route_digest = resolver.digest;
  restart_order.side = OrderSide::Buy;
  restart_order.original_quantity = 65;
  restart_order.effective_quantity = 65;
  restart_order.limit_price_paise = 1000;
  auto restart_started = apply_order_update(
      restart_order, {OrderEventKind::SubmissionStarted, "restart-submit", std::nullopt,
                      std::nullopt, std::nullopt, std::nullopt});
  auto restart_acknowledged = apply_order_update(
      restart_started.aggregate,
      {OrderEventKind::BrokerAcknowledged, "restart-ack", std::string("paper-restart"),
       std::nullopt, std::nullopt, std::nullopt});
  ReconstructedState restart_state;
  restart_state.orders.emplace(restart_order_id, restart_acknowledged.aggregate);
  restart_state.order_route_tokens.emplace(restart_order_id, "58072");
  restart_state.intents.emplace(
      intent().intent_id,
      IntentReplayState{intent().semantic_fingerprint(), 1U, "acknowledged", restart_order_id,
                        false, intent().strategy_id, intent().strategy_run_id,
                        std::nullopt, std::nullopt});
  restart_state.intents.emplace(
      restart_modify_intent,
      IntentReplayState{std::string(64U, 'e'), 2U, "modified", restart_order_id, false,
                        intent().strategy_id, intent().strategy_run_id,
                        std::nullopt, std::nullopt});
  restart_state.last_broker_update_sequence = 2U;
  restart_ledger.replay_state = restart_state;
  BrokerOrderSnapshot restart_snapshot{restart_order_id, intent().canonical_instrument_id,
      "58072", OrderSide::Buy, 65, 1000, 0, "working", "simulated_proxy"};
  restart_broker.orders = {restart_snapshot};
  ReplayedBrokerState restart_replayed;
  restart_replayed.orders = {restart_snapshot};
  restart_replayed.known_instruments.insert(intent().canonical_instrument_id);
  restart_replayed.reconstructed = restart_state;
  ExecutionSession restarted_session(
      "00000000-0000-4000-8000-000000000003", RiskEngine(config()), restart_replayed,
      restart_ledger, resolver, restart_broker, clock);
  expect(restarted_session.start(), "owner-restart fixture startup");
  restarted_session.accept_observation(observation());
  restart_broker.observation_fills = {
      {"restart-fill", restart_order_id, intent().canonical_instrument_id, "58072",
       65, 65, 1000, 951, "simulated_proxy"}};
  auto restart_observation = observation(); restart_observation.receive_timestamp_ns = 951;
  restarted_session.accept_observation(restart_observation);
  const auto restart_fill_record = std::find_if(
      restart_ledger.records.begin(), restart_ledger.records.end(),
      [](const SessionAuditRecord& record) { return record.kind == "filled"; });
  expect(restart_fill_record != restart_ledger.records.end() &&
             restart_fill_record->event.intent_id == intent().intent_id &&
             json_uint64(restart_fill_record->event.payload.at("source_sequence"),
                         "source_sequence") == 3U,
         "restart fill lost canonical place owner or update-sequence continuity");

  const auto durable_restart_root =
      std::filesystem::path("/private/tmp") /
      ("shaurya-section04-session-restart-" + std::to_string(::getpid()));
  const auto durable_restart_path = durable_restart_root / "ledger.jsonl";
  std::error_code cleanup_error;
  static_cast<void>(std::filesystem::remove_all(durable_restart_root, cleanup_error));
  cleanup_error.clear();
  static_cast<void>(std::filesystem::create_directory(durable_restart_root, cleanup_error));
  std::filesystem::permissions(
      durable_restart_root, std::filesystem::perms::owner_all,
      std::filesystem::perm_options::replace, cleanup_error);
  auto restart_rate_config = config();
  restart_rate_config.maximum_orders_per_window = 1;
  restart_rate_config.configuration_digest =
      sha256_hex(restart_rate_config.canonical_payload());
  Broker durable_restart_broker;
  std::optional<SessionIntentResult> original_durable_outcome;
  std::optional<SessionIntentResult> original_rate_rejection;
  {
    auto durable_ledger = ExecutionLedgerSessionAdapter::create_new(durable_restart_path);
    ExecutionSession original_session(
        "00000000-0000-4000-8000-000000000003", RiskEngine(restart_rate_config), {},
        durable_ledger, resolver, durable_restart_broker, clock);
    expect(original_session.start(), "durable-restart original startup");
    original_session.accept_observation(observation());
    original_durable_outcome = original_session.accept_intent(intent());
    expect(risk_approved(original_durable_outcome->decision) &&
               original_durable_outcome->broker_result &&
               durable_restart_broker.mutations == 1U,
           "durable-restart original broker outcome missing");
  }
  {
    auto durable_ledger = ExecutionLedgerSessionAdapter::open_existing(durable_restart_path);
    const auto recovered = *durable_ledger.reconstructed_state();
    ReplayedBrokerState recovered_broker_state;
    recovered_broker_state.orders = durable_restart_broker.orders;
    recovered_broker_state.known_instruments.insert(intent().canonical_instrument_id);
    recovered_broker_state.reconstructed = recovered;
    ExecutionSession recovered_session(
        "00000000-0000-4000-8000-000000000003", RiskEngine(restart_rate_config),
        recovered_broker_state, durable_ledger, resolver, durable_restart_broker, clock);
    expect(recovered_session.start(), "durable-restart recovered startup");
    recovered_session.accept_observation(observation());
    const auto duplicate_after_restart = recovered_session.accept_intent(intent());
    expect(duplicate_after_restart.replayed_duplicate &&
               duplicate_after_restart.decision == original_durable_outcome->decision &&
               duplicate_after_restart.broker_result &&
               duplicate_after_restart.broker_result->status ==
                   original_durable_outcome->broker_result->status &&
               duplicate_after_restart.broker_result->internal_order_id ==
                   original_durable_outcome->broker_result->internal_order_id &&
               duplicate_after_restart.broker_result->broker_correlation_id ==
                   original_durable_outcome->broker_result->broker_correlation_id &&
               duplicate_after_restart.broker_result->provenance ==
                   original_durable_outcome->broker_result->provenance &&
               duplicate_after_restart.broker_result->error ==
                   original_durable_outcome->broker_result->error &&
               duplicate_after_restart.broker_result->terminal_state_confirmed ==
                   original_durable_outcome->broker_result->terminal_state_confirmed &&
               duplicate_after_restart.broker_result->accepted_quantity ==
                   original_durable_outcome->broker_result->accepted_quantity &&
               duplicate_after_restart.broker_result->accepted_limit_price_paise ==
                   original_durable_outcome->broker_result->accepted_limit_price_paise &&
               durable_restart_broker.mutations == 1U,
           "restarted session did not replay the exact prior disposition with zero broker calls");
    auto rate_limited_after_restart = intent();
    rate_limited_after_restart.intent_id = "00000000-0000-4000-8000-000000000092";
    original_rate_rejection = recovered_session.accept_intent(rate_limited_after_restart);
    expect(original_rate_rejection->decision.rejection_code == "order_rate_limit" &&
               durable_restart_broker.mutations == 1U,
           "restart reset the active durable order-rate window");
  }
  {
    auto durable_ledger = ExecutionLedgerSessionAdapter::open_existing(durable_restart_path);
    const auto recovered = *durable_ledger.reconstructed_state();
    ReplayedBrokerState recovered_broker_state;
    recovered_broker_state.orders = durable_restart_broker.orders;
    recovered_broker_state.known_instruments.insert(intent().canonical_instrument_id);
    recovered_broker_state.reconstructed = recovered;
    ExecutionSession recovered_session(
        "00000000-0000-4000-8000-000000000003", RiskEngine(restart_rate_config),
        recovered_broker_state, durable_ledger, resolver, durable_restart_broker, clock);
    expect(recovered_session.start(), "durable rejected-outcome restart startup");
    recovered_session.accept_observation(observation());
    auto rejected_duplicate = intent();
    rejected_duplicate.intent_id = "00000000-0000-4000-8000-000000000092";
    const auto replayed_rejection = recovered_session.accept_intent(rejected_duplicate);
    expect(replayed_rejection.replayed_duplicate && !replayed_rejection.broker_result &&
               replayed_rejection.decision == original_rate_rejection->decision &&
               durable_restart_broker.mutations == 1U,
           "restarted session did not replay the exact prior risk rejection");
  }
  cleanup_error.clear();
  static_cast<void>(std::filesystem::remove_all(durable_restart_root, cleanup_error));

  Broker stop_broker; Ledger stop_ledger;
  ExecutionSession stopping("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                            stop_ledger, resolver, stop_broker, clock);
  expect(stopping.start(), "stop fixture startup"); stopping.accept_observation(observation());
  static_cast<void>(stopping.accept_intent(intent()));
  Coordinator shutdown_coordinator;
  stopping.set_stage_coordinator(&shutdown_coordinator);
  const auto stopped_result = stopping.stop();
  expect(stopped_result.cancel_results.size() == 1U &&
             stopped_result.working_orders_seen == 1U &&
             stopped_result.cancellation_attempts == 1U &&
             stopped_result.cancellation_refusals == 0U &&
             stopped_result.cancellation_accounting_complete &&
             stopped_result.cancellation_complete && stopped_result.reconciliation_exact &&
             stopped_result.ledger_flushed && stopped_result.stopped_recorded,
         "orderly shutdown evidence incomplete");
  expect(shutdown_coordinator.broker_attempted == std::vector<bool>({false, true}),
         "shutdown cancel missed exact pre/post durable broker boundaries");

  Broker bounded_stop_broker; Ledger bounded_stop_ledger;
  ExecutionSession bounded_stop("00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
                                bounded_stop_ledger, resolver, bounded_stop_broker, clock);
  expect(bounded_stop.start(), "bounded-stop fixture startup");
  for (const std::string_view order_id : {
           "00000000-0000-4000-8000-000000000020",
           "00000000-0000-4000-8000-000000000021",
           "00000000-0000-4000-8000-000000000022",
           "00000000-0000-4000-8000-000000000023",
           "00000000-0000-4000-8000-000000000024"}) {
    bounded_stop_broker.orders.push_back(
        {std::string(order_id), intent().canonical_instrument_id, "58072", OrderSide::Buy,
         65, 1000, 0, "working", "simulated_proxy"});
  }
  const auto bounded_result = bounded_stop.stop();
  expect(bounded_result.cancel_results.size() == config().maximum_orders_per_window &&
             bounded_result.working_orders_seen == 5U &&
             bounded_result.cancellation_attempts == config().maximum_orders_per_window &&
             bounded_result.cancellation_refusals == 1U &&
             bounded_result.cancellation_accounting_complete &&
             !bounded_result.cancellation_complete && !bounded_result.reconciliation_exact &&
             bounded_stop.safety_stopped() && bounded_stop.reconciliation_required() &&
             std::count_if(bounded_stop_ledger.records.begin(), bounded_stop_ledger.records.end(),
                           [](const SessionAuditRecord& record) {
                             const auto reason = record.event.payload.find("reason");
                             return record.kind == "reconciliation_required" &&
                                    reason != record.event.payload.end() &&
                                    json_string(reason->second, "reason") ==
                                        "shutdown_cancel_unattempted_rate_limit";
                           }) == 1,
         "shutdown did not durably account for every rate-limited working order");

  Broker deadline_stop_broker; Ledger deadline_stop_ledger;
  ExecutionSession deadline_stop(
      "00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
      deadline_stop_ledger, resolver, deadline_stop_broker, clock);
  expect(deadline_stop.start(), "deadline-stop fixture startup");
  for (const std::string_view order_id : {
           "00000000-0000-4000-8000-000000000025",
           "00000000-0000-4000-8000-000000000026"}) {
    deadline_stop_broker.orders.push_back(
        {std::string(order_id), intent().canonical_instrument_id, "58072", OrderSide::Buy,
         65, 1000, 0, "working", "simulated_proxy"});
  }
  const auto deadline_result = deadline_stop.stop(std::chrono::steady_clock::now());
  expect(deadline_result.working_orders_seen == 2U &&
             deadline_result.cancellation_attempts == 0U &&
             deadline_result.cancellation_refusals == 2U &&
             deadline_result.cancellation_accounting_complete &&
             deadline_result.cancel_results.empty() && !deadline_result.cancellation_complete &&
             !deadline_result.reconciliation_exact && deadline_stop_broker.mutations == 0U &&
             std::count_if(deadline_stop_ledger.records.begin(),
                           deadline_stop_ledger.records.end(),
                           [](const SessionAuditRecord& record) {
                             const auto reason = record.event.payload.find("reason");
                             return record.kind == "reconciliation_required" &&
                                    reason != record.event.payload.end() &&
                                    json_string(reason->second, "reason") ==
                                        "shutdown_cancel_unattempted_deadline";
                           }) == 2,
         "shutdown deadline did not durably account for each unattempted order");

  const auto exercise_pre_attempt_failure =
      [&](std::string_view expected_reason, const auto& inject_failure) {
        Broker failure_broker;
        Ledger failure_ledger;
        Resolver failure_resolver;
        Coordinator failure_coordinator;
        Clock failure_clock;
        ExecutionSession failure_session(
            "00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
            failure_ledger, failure_resolver, failure_broker, failure_clock);
        expect(failure_session.start(), "pre-attempt failure fixture startup");
        failure_broker.orders.push_back(
            {"00000000-0000-4000-8000-000000000027",
             failure_resolver.bank_route.canonical_instrument_id, "58073", OrderSide::Buy,
             15, 1000, 0, "working", "simulated_proxy"});
        failure_broker.orders.push_back(
            {"00000000-0000-4000-8000-000000000028",
             failure_resolver.route.canonical_instrument_id, "58072", OrderSide::Buy,
             65, 1000, 0, "working", "simulated_proxy"});
        inject_failure(failure_broker, failure_ledger, failure_resolver,
                       failure_coordinator, failure_clock);
        failure_session.set_stage_coordinator(&failure_coordinator);
        const auto failure_result = failure_session.stop();
        const auto refusals = std::count_if(
            failure_ledger.records.begin(), failure_ledger.records.end(),
            [&](const SessionAuditRecord& record) {
              const auto reason = record.event.payload.find("reason");
              return record.kind == "reconciliation_required" &&
                     reason != record.event.payload.end() &&
                     json_string(reason->second, "reason") == expected_reason;
            });
        const auto second = std::find_if(
            failure_broker.orders.begin(), failure_broker.orders.end(),
            [](const BrokerOrderSnapshot& order) {
              return order.internal_order_id ==
                     "00000000-0000-4000-8000-000000000028";
            });
        const auto refusal_record = std::find_if(
            failure_ledger.records.begin(), failure_ledger.records.end(),
            [&](const SessionAuditRecord& record) {
              const auto reason = record.event.payload.find("reason");
              return record.kind == "reconciliation_required" &&
                     record.internal_order_id ==
                         "00000000-0000-4000-8000-000000000027" &&
                     reason != record.event.payload.end() &&
                     json_string(reason->second, "reason") == expected_reason;
            });
        const auto later_outcome = std::find_if(
            failure_ledger.records.begin(), failure_ledger.records.end(),
            [](const SessionAuditRecord& record) {
              return record.kind == "cancelled" && record.internal_order_id ==
                  "00000000-0000-4000-8000-000000000028";
            });
        const bool exact_failure_accounting = failure_result.working_orders_seen == 2U &&
                   failure_result.cancellation_attempts == 1U &&
                   failure_result.cancellation_refusals == 1U &&
                   failure_result.cancellation_accounting_complete &&
                   failure_result.cancel_results.size() == 1U &&
                   !failure_result.cancellation_complete &&
                   !failure_result.reconciliation_exact && refusals == 1 &&
                   refusal_record != failure_ledger.records.end() &&
                   later_outcome != failure_ledger.records.end() &&
                   refusal_record < later_outcome &&
                   second != failure_broker.orders.end() && second->state == "cancelled";
        if (!exact_failure_accounting)
          std::cerr << "shutdown failure branch: " << expected_reason << '\n';
        expect(exact_failure_accounting,
               "shutdown early failure omitted or duplicated a later working order");
      };
  exercise_pre_attempt_failure(
      "shutdown_cancel_clock_overflow",
      [](Broker&, Ledger&, Resolver&, Coordinator&, Clock& clock_value) {
        clock_value.overflow_after_calls = 1U;
      });
  exercise_pre_attempt_failure(
      "shutdown_cancel_intent_not_durable",
      [](Broker&, Ledger& ledger_value, Resolver&, Coordinator&, Clock&) {
        ledger_value.fail_kind = "intent_received";
        ledger_value.failures_remaining = 1U;
      });
  exercise_pre_attempt_failure(
      "shutdown_cancel_mapping_unavailable",
      [](Broker&, Ledger&, Resolver& resolver_value, Coordinator&, Clock&) {
        resolver_value.missing.insert(resolver_value.bank_route.canonical_instrument_id);
      });
  exercise_pre_attempt_failure(
      "shutdown_cancel_mapping_exception",
      [](Broker&, Ledger&, Resolver& resolver_value, Coordinator&, Clock&) {
        resolver_value.throwing.insert(resolver_value.bank_route.canonical_instrument_id);
      });
  exercise_pre_attempt_failure(
      "shutdown_cancel_mapping_not_durable",
      [](Broker&, Ledger& ledger_value, Resolver&, Coordinator&, Clock&) {
        ledger_value.fail_kind = "mapping_validated";
        ledger_value.failures_remaining = 1U;
      });
  exercise_pre_attempt_failure(
      "shutdown_cancel_snapshot_unavailable",
      [](Broker& broker_value, Ledger&, Resolver&, Coordinator&, Clock&) {
        broker_value.position_query_failures = 1U;
      });
  exercise_pre_attempt_failure(
      "shutdown_cancel_risk_exception",
      [](Broker&, Ledger&, Resolver&, Coordinator& coordinator_value, Clock&) {
        coordinator_value.risk_evaluation_exceptions = 1U;
      });
  exercise_pre_attempt_failure(
      "shutdown_cancel_risk_refused",
      [](Broker& broker_value, Ledger&, Resolver&, Coordinator&, Clock&) {
        broker_value.lost_health_queries = 1U;
      });
  exercise_pre_attempt_failure(
      "shutdown_cancel_risk_not_durable",
      [](Broker&, Ledger& ledger_value, Resolver&, Coordinator&, Clock&) {
        ledger_value.fail_kind = "risk_approved";
        ledger_value.failures_remaining = 1U;
      });
  exercise_pre_attempt_failure(
      "shutdown_cancel_request_not_durable",
      [](Broker&, Ledger& ledger_value, Resolver&, Coordinator&, Clock&) {
        ledger_value.fail_kind = "cancel_requested";
        ledger_value.failures_remaining = 1U;
      });
  exercise_pre_attempt_failure(
      "shutdown_cancel_boundary_not_acknowledged",
      [](Broker&, Ledger&, Resolver&, Coordinator& coordinator_value, Clock&) {
        coordinator_value.pre_attempt_refusals = 1U;
      });
  exercise_pre_attempt_failure(
      "shutdown_cancel_boundary_not_acknowledged",
      [](Broker&, Ledger&, Resolver&, Coordinator& coordinator_value, Clock&) {
        coordinator_value.pre_attempt_exceptions = 1U;
      });

  {
    Broker refusal_write_broker;
    Ledger refusal_write_ledger;
    Resolver refusal_write_resolver;
    Clock refusal_write_clock;
    ExecutionSession refusal_write_session(
        "00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
        refusal_write_ledger, refusal_write_resolver, refusal_write_broker,
        refusal_write_clock);
    expect(refusal_write_session.start(), "refusal-write fixture startup");
    refusal_write_broker.orders.push_back(
        {"00000000-0000-4000-8000-000000000029",
         refusal_write_resolver.bank_route.canonical_instrument_id, "58073", OrderSide::Buy,
         15, 1000, 0, "working", "simulated_proxy"});
    refusal_write_broker.orders.push_back(
        {"00000000-0000-4000-8000-000000000030",
         refusal_write_resolver.route.canonical_instrument_id, "58072", OrderSide::Buy,
         65, 1000, 0, "working", "simulated_proxy"});
    refusal_write_resolver.missing.insert(
        refusal_write_resolver.bank_route.canonical_instrument_id);
    refusal_write_ledger.fail_kind = "reconciliation_required";
    refusal_write_ledger.failures_remaining = 1U;
    const auto refusal_write_result = refusal_write_session.stop();
    expect(refusal_write_result.working_orders_seen == 2U &&
               refusal_write_result.cancellation_attempts == 1U &&
               refusal_write_result.cancellation_refusals == 0U &&
               !refusal_write_result.cancellation_accounting_complete &&
               !refusal_write_result.cancellation_complete &&
               !refusal_write_result.reconciliation_exact &&
               refusal_write_broker.orders.back().state == "cancelled" &&
               std::none_of(refusal_write_ledger.records.begin(),
                            refusal_write_ledger.records.end(),
                            [](const SessionAuditRecord& record) {
                              return record.kind == "reconciliation_required" &&
                                  record.internal_order_id ==
                                      "00000000-0000-4000-8000-000000000029";
                            }),
           "nondurable refusal was counted or later order accounting stopped");
  }

  for (const auto unhealthy : {BrokerSessionHealth::Degraded, BrokerSessionHealth::Lost,
                               BrokerSessionHealth::Unknown}) {
    Broker health_broker;
    Ledger health_ledger;
    ExecutionSession health_session(
        "00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
        health_ledger, resolver, health_broker, clock);
    expect(health_session.start(), "shutdown-health fixture startup");
    health_broker.health = unhealthy;
    const auto health_result = health_session.stop();
    expect(health_result.cancellation_accounting_complete &&
               health_result.cancellation_complete && !health_result.reconciliation_exact &&
               health_session.reconciliation_required(),
           "unhealthy broker session was labelled exactly reconciled at shutdown");
  }
  for (const auto unhealthy : {BrokerSessionHealth::Degraded, BrokerSessionHealth::Lost,
                               BrokerSessionHealth::Unknown}) {
    for (unsigned query_path = 0U; query_path < 3U; ++query_path) {
      Broker transition_broker;
      Ledger transition_ledger;
      ExecutionSession transition_session(
          "00000000-0000-4000-8000-000000000003", RiskEngine(config()), {},
          transition_ledger, resolver, transition_broker, clock);
      expect(transition_session.start(), "health-transition fixture startup");
      transition_broker.transition_health = unhealthy;
      if (query_path == 0U)
        transition_broker.transition_on_order_query = transition_broker.order_query_calls + 2U;
      else if (query_path == 1U)
        transition_broker.transition_on_trade_query = transition_broker.trade_query_calls + 1U;
      else
        transition_broker.transition_on_position_query =
            transition_broker.position_query_calls + 1U;
      const auto transition_result = transition_session.stop();
      expect(transition_result.cancellation_accounting_complete &&
                 transition_result.cancellation_complete &&
                 !transition_result.reconciliation_exact &&
                 transition_session.reconciliation_required(),
             "post-query broker health transition was labelled exactly reconciled");
    }
  }
  BlockingBroker blocking_broker; Ledger blocking_ledger;
  ExecutionSession blocking_stop("00000000-0000-4000-8000-000000000003", RiskEngine(config()),
                                 {}, blocking_ledger, resolver, blocking_broker, clock);
  const auto blocking_started = std::chrono::steady_clock::now();
  const auto blocking_result = blocking_stop.stop();
  const auto blocking_elapsed = std::chrono::steady_clock::now() - blocking_started;
  expect(blocking_broker.calls == 0U &&
             blocking_elapsed < std::chrono::milliseconds(50) &&
             !blocking_result.reconciliation_exact && blocking_result.stopped_recorded,
         "shutdown called an adapter without a bounded/nonblocking capability");
  PaperBroker scripted_session_broker(PaperFillModel::ScriptedV1, true);
  Ledger scripted_session_ledger;
  ExecutionSession scripted_session("00000000-0000-4000-8000-000000000003",
                                    RiskEngine(config()), {}, scripted_session_ledger,
                                    resolver, scripted_session_broker, clock);
  expect(scripted_session.preflight(), "ScriptedV1 session preflight failed");
  scripted_session.accept_observation(observation());
  const auto scripted_result = scripted_session.accept_intent(intent());
  const auto scripted_orders = scripted_session_broker.query_orders();
  expect(scripted_result.broker_result && scripted_orders.items.size() == 1U,
         "ScriptedV1 authoritative mark did not permit session risk evaluation");
  const auto scripted_fills = scripted_session_broker.apply_scripted({
      {ScriptedPaperEventKind::PartialFill, "scripted-session-1",
       scripted_orders.items.front().internal_order_id, 20U, 1001}});
  const auto scripted_pnl = scripted_session_broker.query_pnl();
  PaperBroker scripted_restarted(scripted_session_broker.snapshot(), true);
  expect(scripted_fills.size() == 1U &&
             scripted_pnl.status == BrokerQueryStatus::Authoritative &&
             scripted_restarted.query_pnl().daily_loss_paise ==
                 scripted_pnl.daily_loss_paise &&
             scripted_restarted.query_pnl().drawdown_paise == scripted_pnl.drawdown_paise,
         "ScriptedV1 partial-fill P&L changed across snapshot restart");
  return failures == 0 ? 0 : 1;
}
