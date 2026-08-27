#include "shaurya/execution/executor.hpp"

#include <iostream>
#include <sys/stat.h>
#include <unistd.h>

using namespace shaurya::execution;

namespace {
struct Clock final : SessionClock {
  std::int64_t value{1000};
  std::int64_t now_ns() const noexcept override { return value; }
};
struct Ledger final : SessionLedger {
  std::vector<SessionAuditRecord> records;
  bool append(const SessionAuditRecord& record) override { records.push_back(record); return true; }
  bool flush() override { return true; }
};
struct Resolver final : SessionRoutingResolver {
  RoutingRecord route{"NSE:NSE_FNO:NIFTY:future:2026-08-27", "58072", "nse_fo",
                      "NIFTY26AUGFUT", 65, 5};
  ResolutionResult resolve(std::string_view canonical) const override {
    if (canonical == route.canonical_instrument_id) return {route, std::nullopt};
    return {std::nullopt, RoutingErrorCode::NotFound};
  }
  std::string_view snapshot_digest() const noexcept override { return digest; }
  bool valid_for_trading_date(std::string_view date) const noexcept override {
    return date == "2026-08-27";
  }
  std::optional<std::int64_t> mapping_timestamp_ns() const noexcept override { return 900; }
  std::string digest = std::string(64U, 'd');
};
struct Broker final : BrokerAdapter {
  unsigned mutations{};
  BrokerMutationResult place(const BrokerOrderRequest& request) override {
    ++mutations; return {BrokerMutationStatus::Acknowledged, request.internal_order_id,
                         "paper-1", "simulated_proxy", std::nullopt, false,
                         request.quantity, request.limit_price_paise};
  }
  BrokerMutationResult modify(const BrokerModifyRequest& request) override {
    ++mutations; return {BrokerMutationStatus::Acknowledged, request.internal_order_id,
                         "paper-2", "simulated_proxy", std::nullopt, false,
                         request.quantity, request.limit_price_paise};
  }
  BrokerMutationResult cancel(std::string_view id) override {
    ++mutations; return {BrokerMutationStatus::Acknowledged, std::string(id),
                         "paper-3", "simulated_proxy", std::nullopt, true,
                         std::nullopt, std::nullopt};
  }
  BrokerQueryResult<BrokerOrderSnapshot> query_orders() const override {
    return {BrokerQueryStatus::Authoritative, {}, "simulated_proxy"};
  }
  BrokerQueryResult<BrokerFillSnapshot> query_trades() const override {
    return {BrokerQueryStatus::Authoritative, {}, "simulated_proxy"};
  }
  BrokerQueryResult<BrokerPositionSnapshot> query_positions() const override {
    return {BrokerQueryStatus::Authoritative, {}, "simulated_proxy"};
  }
  BrokerPnlSnapshot query_pnl() const override {
    return {BrokerQueryStatus::Authoritative, 900, 0, 0, "paper", "simulated_proxy"};
  }
  BrokerSessionHealth session_health() const noexcept override { return BrokerSessionHealth::Ready; }
};
RiskConfiguration risk_config() {
  RiskConfiguration value{"1.0.0", "risk-v1", std::string(64U, '0'), "2026-08-27",
                          100, 100, 100, 5, 130, 260, 1000000000, 4, 4, 1000,
                          100000, 50000, {}};
  value.configuration_digest = sha256_hex(value.canonical_payload());
  return value;
}
StrategyBookObservation book() {
  StrategyBookObservation value;
  value.canonical_instrument_id = "NSE:NSE_FNO:NIFTY:future:2026-08-27";
  value.bids = {{995, 100, 5}}; value.asks = {{1000, 110, 6}};
  value.last_trade_paise = 998; value.cumulative_volume = 10;
  value.last_trade_quantity = 2; value.open_interest = 500;
  value.exchange_timestamp_ns = 940; value.receive_timestamp_ns = 950;
  value.source = "dhan"; value.provenance = "observed";
  return value;
}
MarketObservation observation() { return book().derive_market_observation(); }
OrderIntent intent() {
  OrderIntent value; value.intent_id = "00000000-0000-4000-8000-000000000001";
  value.strategy_id = "d51"; value.strategy_run_id = "00000000-0000-4000-8000-000000000002";
  value.execution_session_id = "00000000-0000-4000-8000-000000000003";
  value.created_at_ns = 900; value.expires_at_ns = 2000;
  value.canonical_instrument_id = observation().canonical_instrument_id;
  value.action = IntentAction::Place; value.side = OrderSide::Buy; value.quantity = 65;
  value.limit_price_paise = 1000; value.product = "NRML"; value.time_in_force = "DAY";
  return value;
}
ExecutorConfiguration executor_config() {
  ExecutorConfiguration value; value.configuration_version = "v1";
  value.configuration_digest = std::string(64U, 'c'); value.mode = "shadow";
  value.trading_date = "2026-08-27"; value.maximum_packet_bytes = 65536U;
  value.queue_capacities.fill(8U); value.io_deadline_ms = 100;
  value.reconnect_window_ms = 100; value.shutdown_deadline_ms = 100;
  value.required_initial_observation_freshness_ns = 1'000'000'000;
  value.execution_session_id = "00000000-0000-4000-8000-000000000003";
  value.expected_strategy_id = "d51"; return value;
}
}

int main() {
  int failures = 0;
  const auto expect = [&](bool value, const char* message) {
    if (!value) { std::cerr << message << '\n'; ++failures; }
  };
  BoundedChannel<int> channel(1U);
  expect(channel.try_push(1) && !channel.try_push(2), "queue is not bounded");
  expect(channel.metrics().depth == 1U && channel.metrics().high_water == 1U,
         "queue metrics invalid");

  Clock clock; Resolver resolver; Broker broker;
  char pattern[] = "/private/tmp/shaurya-executor-queues-XXXXXX";
  const char* made = ::mkdtemp(pattern); if (made == nullptr) return 1;
  const std::filesystem::path runtime(made); (void)::chmod(runtime.c_str(), 0700);
  auto configured = executor_config(); configured.ledger_path = runtime / "events.ledger";
  auto audit = ExecutionLedgerSessionAdapter::create_new(configured.ledger_path);
  ExecutionSession session("00000000-0000-4000-8000-000000000003", RiskEngine(risk_config()), {},
                           audit, resolver, broker, clock);
  expect(session.preflight() && !session.ready(), "session became ready before a market peer/book");
  Executor executor(configured, session, audit.ledger(), clock);
  const std::string executable(64U, 'a'), configuration(64U, 'c');
  const auto authenticate = [&](Executor& target, PeerRole role) {
    ExpectedPeerIdentity expected{role, 10U, 20U, executable, configuration, "1.0.0",
                                  intent().execution_session_id};
    PeerHandshakeBindings bindings{role, "1.0.0", intent().execution_session_id, configuration,
                                   executable, "start", "nonce"};
    IpcHandshake handshake{bindings, std::nullopt,
                           role == PeerRole::StrategyClient ? std::optional<std::string>("d51")
                                                            : std::nullopt};
    InjectedPeerInspector inspector({PeerPlatform::Linux, 10U, 20U, 42, "start", executable, true});
    target.authenticate_peer(expected, handshake, inspector, -1);
  };
  authenticate(executor, PeerRole::MarketPublisher); authenticate(executor, PeerRole::StrategyClient);
  IpcEnvelope market{IpcMessageKind::StrategyBookObservation, intent().execution_session_id,
                     std::nullopt, std::nullopt, std::nullopt, book().to_json(), std::nullopt};
  const auto relay = executor.accept_market(market);
  expect(relay.strategy_book && relay.strategy_book->source_sequence == 1U &&
         relay.strategy_book->source_digest == sha256_hex(book().to_json()),
         "strategy book rejected");
  const auto second_relay = executor.accept_market(market);
  expect(second_relay.strategy_book && second_relay.strategy_book->source_sequence == 2U &&
         second_relay.strategy_book->source_digest == relay.strategy_book->source_digest,
         "executor did not assign deterministic monotonic source correlation");
  IpcEnvelope order{IpcMessageKind::OrderIntent, intent().execution_session_id, "d51",
                    std::nullopt, std::nullopt, intent().to_json(), std::nullopt};
  const auto events = executor.accept_intent(order);
  if (events.size() != 5U || broker.mutations != 1U)
    std::cerr << "intent diagnostics events=" << events.size() << " mutations=" << broker.mutations
              << (events.empty() ? std::string() : " payload=" + events.front().canonical_payload) << '\n';
  expect(events.size() == 5U && broker.mutations == 1U, "intent flow not executed exactly once");
  expect(executor.reconnect(0U, intent().execution_session_id, "d51").size() ==
             audit.ledger().last_sequence(),
         "reconnect did not replay durable event sequence");
  expect(executor.accept_intent(order).size() == events.size() && broker.mutations == 1U,
         "restart-style duplicate intent resubmitted broker mutation");
  const auto ledger_before_bad_binding = audit.ledger().last_sequence();
  auto wrong_session_intent = intent();
  wrong_session_intent.execution_session_id = "00000000-0000-4000-8000-000000000090";
  auto wrong_session_envelope = order;
  wrong_session_envelope.canonical_payload = wrong_session_intent.to_json();
  bool wrong_session_refused = false;
  try { static_cast<void>(executor.submit_intent_from_reader(wrong_session_envelope)); }
  catch (const IpcProtocolError&) { wrong_session_refused = true; }
  auto wrong_run_intent = intent();
  wrong_run_intent.strategy_run_id = "00000000-0000-4000-8000-000000000091";
  auto wrong_run_envelope = order;
  wrong_run_envelope.canonical_payload = wrong_run_intent.to_json();
  bool wrong_run_refused = false;
  try { static_cast<void>(executor.submit_intent_from_reader(wrong_run_envelope)); }
  catch (const IpcProtocolError&) { wrong_run_refused = true; }
  expect(wrong_session_refused && wrong_run_refused &&
             audit.ledger().last_sequence() == ledger_before_bad_binding,
         "inner strategy/session/run binding reached durable intent ingress");

  auto not_ready_config = executor_config();
  not_ready_config.ledger_path = runtime / "not-ready-events.ledger";
  auto not_ready_audit = ExecutionLedgerSessionAdapter::create_new(not_ready_config.ledger_path);
  Broker not_ready_broker;
  ExecutionSession not_ready_session(intent().execution_session_id, RiskEngine(risk_config()), {},
                                     not_ready_audit, resolver, not_ready_broker, clock);
  expect(not_ready_session.preflight(), "not-ready fixture preflight failed");
  Executor not_ready_executor(not_ready_config, not_ready_session, not_ready_audit.ledger(), clock);
  authenticate(not_ready_executor, PeerRole::MarketPublisher);
  authenticate(not_ready_executor, PeerRole::StrategyClient);
  const auto not_ready_events = not_ready_executor.accept_intent(order);
  expect(not_ready_broker.mutations == 0U &&
             std::any_of(not_ready_events.begin(), not_ready_events.end(),
                         [](const IpcEnvelope& item) {
                           return ExecutionEvent::parse(item.canonical_payload).event_type ==
                                  "risk_rejected";
                         }),
         "pre-readiness intent was not durably refused before any broker attempt");
  expect(not_ready_executor.queue_metrics(ExecutorQueueKind::OutboundEvent).depth ==
             not_ready_events.size(),
         "outbound events were released before an explicit acknowledgement");
  const auto not_ready_last = not_ready_audit.ledger().last_sequence();
  not_ready_executor.mark_event_delivered(not_ready_last);
  not_ready_executor.acknowledge_events_through(not_ready_last);
  expect(not_ready_executor.queue_metrics(ExecutorQueueKind::OutboundEvent).depth == 0U,
         "explicit acknowledgement did not release retained events");
  bool regressing_ack_refused = false;
  try { not_ready_executor.acknowledge_events_through(not_ready_last - 1U); }
  catch (const IpcProtocolError&) { regressing_ack_refused = true; }
  bool ahead_ack_refused = false;
  try { not_ready_executor.acknowledge_events_through(not_ready_last + 1U); }
  catch (const IpcProtocolError&) { ahead_ack_refused = true; }
  expect(regressing_ack_refused && ahead_ack_refused,
         "regressing or ahead-of-delivery acknowledgement was accepted");

  auto unhealthy_config = executor_config();
  unhealthy_config.ledger_path = runtime / "unhealthy-events.ledger";
  auto unhealthy_audit = ExecutionLedgerSessionAdapter::create_new(unhealthy_config.ledger_path);
  Broker unhealthy_broker;
  ExecutionSession unhealthy_session(intent().execution_session_id, RiskEngine(risk_config()), {},
                                     unhealthy_audit, resolver, unhealthy_broker, clock);
  expect(unhealthy_session.preflight(), "unhealthy fixture preflight failed");
  Executor unhealthy_executor(unhealthy_config, unhealthy_session, unhealthy_audit.ledger(), clock);
  authenticate(unhealthy_executor, PeerRole::MarketPublisher);
  authenticate(unhealthy_executor, PeerRole::StrategyClient);
  auto crossed = book();
  crossed.quality_flags = {"stale"};
  IpcEnvelope crossed_envelope{IpcMessageKind::StrategyBookObservation,
                               intent().execution_session_id, std::nullopt, std::nullopt,
                               std::nullopt, crossed.to_json(), std::nullopt};
  expect(unhealthy_executor.submit_intent_from_reader(order) &&
             unhealthy_executor.submit_market_from_reader(crossed_envelope) &&
             unhealthy_executor.next_market_is_safety_fault(),
         "simultaneous safety input was not visible before strategy work");
  const auto rejected_book = unhealthy_executor.process_next_market();
  expect(!rejected_book.strategy_book && unhealthy_executor.safety_stopped() &&
             unhealthy_broker.mutations == 0U && !unhealthy_executor.ready(),
         "unhealthy first book established readiness or allowed broker work");

  Clock stale_clock; Ledger stale_audit; Broker stale_broker;
  ExecutionSession stale_session(intent().execution_session_id, RiskEngine(risk_config()), {},
                                 stale_audit, resolver, stale_broker, stale_clock);
  expect(stale_session.preflight(), "stale fixture preflight failed");
  auto stale_config = executor_config();
  stale_config.ledger_path = runtime / "stale-events.ledger";
  auto stale_ledger = ExecutionLedger::create_new(stale_config.ledger_path);
  Executor stale_executor(stale_config, stale_session, stale_ledger, stale_clock);
  authenticate(stale_executor, PeerRole::MarketPublisher);
  authenticate(stale_executor, PeerRole::StrategyClient);
  (void)stale_executor.accept_market(market);
  stale_clock.value = 1'000'002'000;
  auto stale_intent = intent();
  stale_intent.intent_id = "00000000-0000-4000-8000-000000000099";
  IpcEnvelope stale_order{IpcMessageKind::OrderIntent, intent().execution_session_id, "d51",
                          std::nullopt, std::nullopt, stale_intent.to_json(), std::nullopt};
  expect(stale_executor.accept_intent(stale_order).empty() && stale_executor.safety_stopped() &&
             stale_broker.mutations == 0U,
         "market inactivity did not refuse intent before broker mutation");

  IpcEnvelope marker{IpcMessageKind::ExecutionEvent, intent().execution_session_id, "d51",
                     std::nullopt, 1U, events.front().canonical_payload, std::nullopt};
  while (executor.enqueue(ExecutorQueueKind::MarketReceive, marker)) {}
  expect(executor.safety_stopped(),
         "overflow did not stop executor");
  const auto first_reason = executor.safety_reason();
  (void)executor.enqueue(ExecutorQueueKind::BrokerUpdate, marker, true);
  expect(executor.safety_reason() == first_reason, "later failure overwrote first safety reason");

  for (std::size_t index = 0; index < static_cast<std::size_t>(ExecutorQueueKind::Count); ++index) {
    const auto kind = static_cast<ExecutorQueueKind>(index);
    while (executor.enqueue(kind, marker)) {}
    const auto metrics = executor.queue_metrics(kind);
    expect(metrics.depth == metrics.capacity && metrics.high_water == metrics.capacity,
           "stage queue did not saturate deterministically");
    expect(executor.safety_reason() == first_reason, "stage overflow changed first failure");
  }

  Ledger pre_audit; Broker pre_broker;
  ExecutionSession pre_session(intent().execution_session_id, RiskEngine(risk_config()), {},
                               pre_audit, resolver, pre_broker, clock);
  expect(pre_session.start(), "pre-broker fixture start failed");
  auto pre_config = executor_config(); pre_config.queue_capacities.fill(1U);
  pre_config.ledger_path = runtime / "pre-events.ledger";
  auto pre_ledger = ExecutionLedger::create_new(pre_config.ledger_path);
  Executor pre_executor(pre_config, pre_session, pre_ledger, clock);
  expect(pre_executor.enqueue(ExecutorQueueKind::BrokerSubmission, marker) &&
         !pre_executor.enqueue(ExecutorQueueKind::BrokerSubmission, marker),
         "pre-broker queue did not overflow");
  authenticate(pre_executor, PeerRole::MarketPublisher);
  authenticate(pre_executor, PeerRole::StrategyClient);
  (void)pre_executor.accept_market(market);
  (void)pre_executor.accept_intent(order);
  expect(pre_broker.mutations == 0U, "pre-broker overflow sent an order");

  Broker post_broker;
  auto post_config = executor_config(); post_config.queue_capacities.fill(4U);
  post_config.queue_capacities[static_cast<std::size_t>(ExecutorQueueKind::OutboundEvent)] = 8U;
  post_config.ledger_path = runtime / "post-events.ledger";
  auto post_audit = ExecutionLedgerSessionAdapter::create_new(post_config.ledger_path);
  ExecutionSession post_session(intent().execution_session_id, RiskEngine(risk_config()), {},
                                post_audit, resolver, post_broker, clock);
  expect(post_session.preflight(), "post-broker fixture start failed");
  Executor post_executor(post_config, post_session, post_audit.ledger(), clock);
  authenticate(post_executor, PeerRole::MarketPublisher);
  authenticate(post_executor, PeerRole::StrategyClient);
  const auto post_market = post_executor.accept_market(market);
  expect(post_market.execution_events.size() == 2U &&
             ExecutionEvent::parse(post_market.execution_events.front().canonical_payload)
                     .event_type == "market_observation_accepted" &&
             ExecutionEvent::parse(post_market.execution_events.back().canonical_payload)
                     .event_type == "session_started",
         "market evidence/readiness events missing");
  post_executor.mark_event_delivered(post_audit.ledger().last_sequence());
  post_executor.acknowledge_events_through(post_audit.ledger().last_sequence());
  expect(post_executor.submit_intent_from_reader(order), "post-broker intent ingress failed");
  (void)post_executor.process_next_intent();
  const auto prepared_delivery = post_executor.process_next_risk_work();
  expect(!prepared_delivery.empty(), "pre-broker evidence was not produced");
  post_executor.mark_event_delivered(post_audit.ledger().last_sequence());
  post_executor.acknowledge_events_through(post_audit.ledger().last_sequence());
  for (std::size_t index = 0; index < 8U; ++index)
    expect(post_executor.enqueue(ExecutorQueueKind::OutboundEvent, marker),
           "post-broker outbound saturation setup failed");
  const auto partial_delivery = post_executor.process_next_broker_submission();
  expect(post_broker.mutations == 1U && partial_delivery.empty() &&
         post_executor.safety_reason() == std::optional<std::string>("post_broker_overflow_ambiguous"),
         "post-broker overflow was not recorded as ambiguous");
  expect(post_executor.reconnect(0U, intent().execution_session_id, "d51").size() ==
             post_audit.ledger().last_sequence(),
         "failed delivery was not replayable from ledger");

  auto readiness_config = executor_config(); readiness_config.queue_capacities.fill(4U);
  readiness_config.queue_capacities[static_cast<std::size_t>(ExecutorQueueKind::OutboundEvent)] = 1U;
  readiness_config.ledger_path = runtime / "readiness-overflow.ledger";
  auto readiness_audit = ExecutionLedgerSessionAdapter::create_new(readiness_config.ledger_path);
  Broker readiness_broker;
  ExecutionSession readiness_session(intent().execution_session_id, RiskEngine(risk_config()), {},
                                     readiness_audit, resolver, readiness_broker, clock);
  expect(readiness_session.preflight(), "readiness-overflow preflight failed");
  Executor readiness_executor(readiness_config, readiness_session, readiness_audit.ledger(), clock);
  authenticate(readiness_executor, PeerRole::MarketPublisher);
  authenticate(readiness_executor, PeerRole::StrategyClient);
  IpcEnvelope readiness_marker{IpcMessageKind::ExecutionEvent, intent().execution_session_id,
                               "d51", std::nullopt, 1U,
                               ExecutionEvent::parse(events.front().canonical_payload).to_json(),
                               std::nullopt};
  expect(readiness_executor.enqueue(ExecutorQueueKind::OutboundEvent, readiness_marker),
         "readiness-overflow setup failed");
  (void)readiness_executor.accept_market(market);
  expect(readiness_executor.safety_reason() ==
             std::optional<std::string>("outbound_event_overflow"),
         "readiness-only outbound overflow was falsely classified post-broker ambiguous");

  auto disconnect_config = executor_config();
  disconnect_config.ledger_path = runtime / "market-disconnect.ledger";
  auto disconnect_audit = ExecutionLedgerSessionAdapter::create_new(disconnect_config.ledger_path);
  Broker disconnect_broker;
  ExecutionSession disconnect_session(intent().execution_session_id, RiskEngine(risk_config()), {},
                                      disconnect_audit, resolver, disconnect_broker, clock);
  expect(disconnect_session.preflight(), "market-disconnect preflight failed");
  Executor disconnect_executor(disconnect_config, disconnect_session,
                               disconnect_audit.ledger(), clock);
  authenticate(disconnect_executor, PeerRole::MarketPublisher);
  authenticate(disconnect_executor, PeerRole::StrategyClient);
  (void)disconnect_executor.accept_market(market);
  expect(disconnect_executor.ready(), "market-disconnect fixture never became ready");
  disconnect_executor.record_peer_disconnect(PeerRole::MarketPublisher);
  expect(!disconnect_executor.ready() && disconnect_executor.safety_reason() ==
             std::optional<std::string>("market_peer_disconnected"),
         "market disconnect did not permanently revoke order authority");
  BrokerUpdateEnvelope reserved_update;
  reserved_update.sequence = 1U;
  reserved_update.update_id = "reserved-update-1";
  expect(disconnect_executor.reserve_broker_updates(3U) &&
             disconnect_executor.dispatch_broker_update(std::move(reserved_update)),
         "broker-update reservation fixture failed");
  disconnect_executor.release_broker_update_reservations();
  expect(disconnect_executor.queue_metrics(ExecutorQueueKind::BrokerUpdate).depth == 1U,
         "partially consumed broker-update reservations were not removed in place");

  const auto recovery_path = runtime / "recovery-events.ledger";
  {
    auto live_audit = ExecutionLedgerSessionAdapter::create_new(recovery_path);
    PaperBroker live_broker;
    ExecutionSession live_session(intent().execution_session_id, RiskEngine(risk_config()), {},
                                  live_audit, resolver, live_broker, clock);
    expect(live_session.preflight(), "recovery fixture preflight failed");
    auto recovery_config = executor_config(); recovery_config.ledger_path = recovery_path;
    Executor live_executor(recovery_config, live_session, live_audit.ledger(), clock);
    authenticate(live_executor, PeerRole::MarketPublisher);
    authenticate(live_executor, PeerRole::StrategyClient);
    (void)live_executor.accept_market(market);
    expect(live_executor.accept_intent(order).size() == 5U &&
               live_broker.query_orders().items.size() == 1U,
           "recovery fixture did not durably place a working order");
  }
  const auto recovered = recover_paper_broker(
      verify_ledger(recovery_path, LedgerVerificationMode::RetainRecords));
  PaperBroker reopened_broker(recovered.snapshot);
  auto reopened_audit = ExecutionLedgerSessionAdapter::open_existing(recovery_path);
  ExecutionSession reopened_session(intent().execution_session_id, RiskEngine(risk_config()),
                                    recovered.replayed, reopened_audit, resolver,
                                    reopened_broker, clock);
  expect(reopened_session.preflight(), "real factory-style paper reopen did not reconcile");
  auto first_after_restart = observation();
  first_after_restart.receive_timestamp_ns = 1001;
  first_after_restart.exchange_timestamp_ns = 1001;
  first_after_restart.cumulative_volume = 1000;
  expect(reopened_broker.accept_observation(first_after_restart).empty(),
         "real ledger reopen overfilled on its first accumulated-volume observation");
  first_after_restart.receive_timestamp_ns = 1002;
  first_after_restart.exchange_timestamp_ns = 1002;
  first_after_restart.cumulative_volume = 1007;
  const auto recovered_fill = reopened_broker.accept_observation(first_after_restart);
  expect(recovered_fill.size() == 1U && recovered_fill.front().last_fill_quantity == 65U,
         "real ledger reopen did not require a later volume delta before full fill");

  auto shutdown_config = executor_config();
  shutdown_config.ledger_path = runtime / "shutdown-drain.ledger";
  shutdown_config.queue_capacities[static_cast<std::size_t>(ExecutorQueueKind::RiskWork)] = 1U;
  auto shutdown_audit = ExecutionLedgerSessionAdapter::create_new(shutdown_config.ledger_path);
  Broker shutdown_broker;
  ExecutionSession shutdown_session(intent().execution_session_id, RiskEngine(risk_config()), {},
                                    shutdown_audit, resolver, shutdown_broker, clock);
  expect(shutdown_session.preflight(), "shutdown-drain preflight failed");
  Executor shutdown_executor(shutdown_config, shutdown_session, shutdown_audit.ledger(), clock);
  authenticate(shutdown_executor, PeerRole::MarketPublisher);
  authenticate(shutdown_executor, PeerRole::StrategyClient);
  static_cast<void>(shutdown_executor.accept_market(market));
  for (std::uint64_t suffix = 80U; suffix < 83U; ++suffix) {
    auto queued_intent = intent();
    queued_intent.intent_id = "00000000-0000-4000-8000-0000000000" +
                              std::to_string(suffix);
    auto queued_envelope = order;
    queued_envelope.canonical_payload = queued_intent.to_json();
    expect(shutdown_executor.submit_intent_from_reader(std::move(queued_envelope)),
           "shutdown-drain accepted ingress setup failed");
  }
  const auto shutdown_result = shutdown_executor.shutdown();
  const auto shutdown_records =
      shutdown_audit.ledger().verify(LedgerVerificationMode::RetainRecords);
  expect(shutdown_broker.mutations == 0U && shutdown_result.stopped_recorded &&
             shutdown_executor.queue_metrics(ExecutorQueueKind::StrategyReceive).depth == 0U &&
             shutdown_executor.queue_metrics(ExecutorQueueKind::RiskWork).depth == 0U &&
             shutdown_executor.queue_metrics(ExecutorQueueKind::BrokerSubmission).depth == 0U &&
             std::count_if(shutdown_records.records.begin(), shutdown_records.records.end(),
                           [](const LedgerRecord& record) {
                             return record.event.event_type == "risk_rejected";
                           }) == 3 &&
             !shutdown_executor.shutdown_succeeded(),
         "shutdown did not durably refuse accepted work or exposed success with unacked output");
  std::filesystem::remove_all(runtime);
  return failures == 0 ? 0 : 1;
}
