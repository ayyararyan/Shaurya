#include "shaurya/execution/canonical_json.hpp"
#include "shaurya/execution/executor.hpp"

#include <filesystem>
#include <iostream>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <thread>
#include <unistd.h>

using namespace shaurya::execution;

namespace {
struct Clock final : SessionClock {
  std::atomic<std::int64_t> value{1000};
  std::int64_t now_ns() const noexcept override { return value.load(); }
};
struct Ledger final : SessionLedger {
  bool append(const SessionAuditRecord&) override { return true; }
  bool flush() override { return true; }
};
struct Resolver final : SessionRoutingResolver {
  RoutingRecord route{"NSE:NSE_FNO:NIFTY:future:2026-08-27", "58072", "nse_fo",
                      "NIFTY26AUGFUT", 65, 5};
  ResolutionResult resolve(std::string_view id) const override {
    return id == route.canonical_instrument_id ? ResolutionResult{route, std::nullopt}
                                                : ResolutionResult{std::nullopt, RoutingErrorCode::NotFound};
  }
  std::string_view snapshot_digest() const noexcept override { return digest; }
  bool valid_for_trading_date(std::string_view date) const noexcept override { return date == "2026-08-27"; }
  std::optional<std::int64_t> mapping_timestamp_ns() const noexcept override { return 900; }
  std::string digest = std::string(64U, 'd');
};
struct Broker final : BrokerAdapter {
  unsigned places{};
  BrokerMutationResult place(const BrokerOrderRequest& request) override {
    ++places; return {BrokerMutationStatus::Acknowledged, request.internal_order_id,
                      "paper-1", "simulated_proxy", std::nullopt, false,
                      request.quantity, request.limit_price_paise};
  }
  BrokerMutationResult modify(const BrokerModifyRequest& request) override {
    return {BrokerMutationStatus::Acknowledged, request.internal_order_id,
            "paper-2", "simulated_proxy", std::nullopt, false,
            request.quantity, request.limit_price_paise};
  }
  BrokerMutationResult cancel(std::string_view id) override {
    return {BrokerMutationStatus::Acknowledged, std::string(id),
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
struct SlowInspector final : PeerInspector {
  SlowInspector(PeerEvidence value, std::chrono::milliseconds wait)
      : evidence(std::move(value)), delay(wait) {}
  PeerEvidence evidence;
  std::chrono::milliseconds delay;
  PeerEvidence inspect(int) const override {
    std::this_thread::sleep_for(delay);
    return evidence;
  }
};
RiskConfiguration risk() {
  RiskConfiguration value{"1.0.0", "risk-v1", std::string(64U, '0'), "2026-08-27",
                          100, 100, 100, 5, 130, 260, 1000000000, 4, 4, 1000,
                          100000, 50000, {}};
  value.configuration_digest = sha256_hex(value.canonical_payload());
  return value;
}
StrategyBookObservation book(std::uint64_t volume = 10U, std::int64_t receive_timestamp = 950) {
  StrategyBookObservation value;
  value.canonical_instrument_id = "NSE:NSE_FNO:NIFTY:future:2026-08-27";
  value.bids = {{995, 100, 5}, {990, 90, 4}, {985, 80, 3}, {980, 70, 2}, {975, 60, 1}};
  value.asks = {{1000, 110, 6}, {1005, 120, 7}, {1010, 130, 8}, {1015, 140, 9},
                {1020, 150, 10}};
  value.last_trade_paise = 998; value.cumulative_volume = volume;
  value.last_trade_quantity = 2; value.open_interest = 500;
  value.exchange_timestamp_ns = receive_timestamp - 10;
  value.receive_timestamp_ns = receive_timestamp;
  value.source = "dhan"; value.provenance = "observed"; return value;
}
MarketObservation observation() { return book().derive_market_observation(); }
OrderIntent intent() {
  OrderIntent value; value.intent_id = "00000000-0000-4000-8000-000000000001";
  value.strategy_id = "d51"; value.strategy_run_id = "00000000-0000-4000-8000-000000000002";
  value.execution_session_id = "00000000-0000-4000-8000-000000000003";
  value.created_at_ns = 900; value.expires_at_ns = 2000;
  value.canonical_instrument_id = observation().canonical_instrument_id;
  value.action = IntentAction::Place; value.side = OrderSide::Buy; value.quantity = 65;
  value.limit_price_paise = 1000; value.product = "NRML"; value.time_in_force = "DAY"; return value;
}
int connect_unix(const std::filesystem::path& path, IpcSocketMode mode) {
  const int descriptor = ::socket(AF_UNIX, mode == IpcSocketMode::SeqPacket ? SOCK_SEQPACKET : SOCK_STREAM, 0);
  if (descriptor < 0) throw std::runtime_error("fixture_socket_failed");
  sockaddr_un address{}; address.sun_family = AF_UNIX;
  const auto path_text = path.string();
  if (path_text.size() >= sizeof(address.sun_path)) throw std::runtime_error("fixture_path_long");
  std::copy(path_text.begin(), path_text.end(), address.sun_path);
  if (::connect(descriptor, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) != 0)
    throw std::runtime_error("fixture_connect_failed");
  return descriptor;
}
std::string challenge_nonce(int descriptor, IpcSocketMode mode, const IpcFrameCodec& codec) {
  const auto bytes = read_ipc_frame(descriptor, mode, codec, std::chrono::milliseconds(500));
  return json_string(json_object(parse_json(bytes), "challenge").at("nonce"), "nonce");
}
void send_handshake(int descriptor, IpcSocketMode mode, const IpcFrameCodec& codec,
                    PeerRole role, std::string nonce, std::optional<std::uint64_t> cursor = {},
                    std::string strategy_id = "d51") {
  JsonObject document{{"configuration_digest", JsonValue(std::string(64U, 'c'))},
                      {"execution_session_id", JsonValue(intent().execution_session_id)},
                      {"executable_digest", JsonValue(std::string(64U, 'e'))},
                      {"nonce", JsonValue(std::move(nonce))},
                      {"process_start_identity", JsonValue(std::string("fixture-start"))},
                      {"protocol_version", JsonValue(std::string("1.0.0"))},
                      {"role", JsonValue(std::string(role == PeerRole::MarketPublisher
                                                         ? "market_publisher" : "strategy_client"))},
                      {"schema_version", JsonValue(std::string("1.0.0"))}};
  if (role == PeerRole::StrategyClient)
    document.emplace("strategy_id", JsonValue(std::move(strategy_id)));
  if (cursor) document.emplace("after_event_sequence", JsonValue(JsonInteger{std::to_string(*cursor)}));
  write_ipc_frame(descriptor, mode, codec, canonical_json(JsonValue(std::move(document))),
                  std::chrono::milliseconds(500));
}
void send_ack(int descriptor, IpcSocketMode mode, const IpcFrameCodec& codec,
              std::string_view session, std::uint64_t sequence) {
  const EventAcknowledgement acknowledgement{sequence};
  const IpcEnvelope envelope{IpcMessageKind::EventAcknowledgement, std::string(session), "d51",
                             std::nullopt, sequence, acknowledgement.to_json(), std::nullopt};
  write_ipc_frame(descriptor, mode, codec, encode_ipc_envelope(envelope),
                  std::chrono::milliseconds(500));
}
}

int main() {
  int failures = 0;
  const auto expect = [&](bool value, const char* message) {
    if (!value) { std::cerr << message << '\n'; ++failures; }
  };
  char pattern[] = "/private/tmp/shaurya-executor-e2e-XXXXXX";
  const char* made = ::mkdtemp(pattern); if (made == nullptr) return 1;
  const std::filesystem::path runtime(made); (void)::chmod(runtime.c_str(), 0700);
  ExecutorConfiguration config; config.configuration_version = "v1";
  config.configuration_digest = std::string(64U, 'c'); config.mode = "shadow";
  config.trading_date = "2026-08-27"; config.runtime_directory = runtime;
  config.market_socket_basename = "market.sock"; config.strategy_socket_basename = "strategy.sock";
  config.maximum_packet_bytes = 65536U; config.queue_capacities.fill(8U);
  config.io_deadline_ms = 20; config.reconnect_window_ms = 500; config.shutdown_deadline_ms = 500;
  config.required_initial_observation_freshness_ns = 1'000'000'000;
  config.execution_session_id = intent().execution_session_id; config.expected_strategy_id = "d51";
  config.ledger_path = runtime / "events.ledger";
  Clock clock; Resolver resolver; PaperBroker broker;
  auto audit = ExecutionLedgerSessionAdapter::create_new(config.ledger_path);
  ExecutionSession session(config.execution_session_id, RiskEngine(risk()), {}, audit, resolver,
                           broker, clock);
  expect(session.preflight() && !session.ready(),
         "fixture session became ready before peers and fresh book");
  Executor executor(config, session, audit.ledger(), clock);
  const PeerEvidence evidence{PeerPlatform::Darwin, 10U, 20U, -1, "fixture-start", {}, false};
  InjectedPeerInspector market_inspector(evidence), strategy_inspector(evidence);
  ExpectedPeerIdentity market_identity{PeerRole::MarketPublisher, 10U, 20U, std::string(64U, 'e'),
                                       std::string(64U, 'c'), "1.0.0", config.execution_session_id};
  auto strategy_identity = market_identity; strategy_identity.role = PeerRole::StrategyClient;
  ExecutorServer server(executor, config, market_identity, strategy_identity,
                        market_inspector, strategy_inspector, false);
#if defined(__APPLE__)
  constexpr auto mode = IpcSocketMode::Stream;
#else
  constexpr auto mode = IpcSocketMode::SeqPacket;
#endif
  IpcFrameCodec codec;
  std::exception_ptr worker_error;
  std::thread worker([&] {
    try { server.run(); }
    catch (const std::exception& exception) {
      std::cerr << "executor server failed: " << exception.what() << '\n';
      worker_error = std::current_exception();
    }
  });
  int market = connect_unix(server.market_socket_path(), mode);
  send_handshake(market, mode, codec, PeerRole::MarketPublisher,
                 challenge_nonce(market, mode, codec));
  int refused_strategy = connect_unix(server.strategy_socket_path(), mode);
  send_handshake(refused_strategy, mode, codec, PeerRole::StrategyClient,
                 challenge_nonce(refused_strategy, mode, codec), std::nullopt, "other-strategy");
  (void)::close(refused_strategy);
  int strategy = connect_unix(server.strategy_socket_path(), mode);
  send_handshake(strategy, mode, codec, PeerRole::StrategyClient,
                 challenge_nonce(strategy, mode, codec));
  const auto startup_reconciliation = parse_ipc_envelope(read_ipc_frame(
      strategy, mode, codec, std::chrono::milliseconds(500)));
  expect(ExecutionEvent::parse(startup_reconciliation.canonical_payload).event_type ==
             "reconciliation_completed" && !session.ready(),
         "initial replay/readiness ordering invalid");
  send_ack(strategy, mode, codec, config.execution_session_id,
           *startup_reconciliation.event_sequence);
  auto refused_intent = intent();
  refused_intent.intent_id = "00000000-0000-4000-8000-000000000099";
  const IpcEnvelope refused_order_packet{IpcMessageKind::OrderIntent,
      config.execution_session_id, "d51", std::nullopt, std::nullopt,
      refused_intent.to_json(), std::nullopt};
  write_ipc_frame(strategy, mode, codec, encode_ipc_envelope(refused_order_packet),
                  std::chrono::milliseconds(500));
  std::uint64_t refused_cursor = 0U;
  bool durable_prebook_refusal = false;
  for (int index = 0; index < 3; ++index) {
    const auto item = parse_ipc_envelope(read_ipc_frame(
        strategy, mode, codec, std::chrono::milliseconds(500)));
    refused_cursor = *item.event_sequence;
    durable_prebook_refusal = durable_prebook_refusal ||
        ExecutionEvent::parse(item.canonical_payload).event_type == "risk_rejected";
  }
  expect(durable_prebook_refusal && broker.query_orders().items.empty(),
         "pre-book intent was not durably refused without broker work");
  send_ack(strategy, mode, codec, config.execution_session_id, refused_cursor);
  const IpcEnvelope market_packet{IpcMessageKind::StrategyBookObservation,
                                  config.execution_session_id, std::nullopt, std::nullopt,
                                  std::nullopt, book().to_json(), std::nullopt};
  write_ipc_frame(market, mode, codec, encode_ipc_envelope(market_packet), std::chrono::milliseconds(500));
  const auto first_market_envelope = parse_ipc_envelope(read_ipc_frame(
      strategy, mode, codec, std::chrono::milliseconds(500)));
  const auto first_market_evidence = ExecutionEvent::parse(first_market_envelope.canonical_payload);
  expect(first_market_evidence.event_type == "market_observation_accepted" &&
             json_uint64(first_market_evidence.payload.at("source_sequence"),
                         "source_sequence") == 1U,
         "initial market observation evidence was not durable before relay");
  const auto relayed_book = parse_ipc_envelope(read_ipc_frame(
      strategy, mode, codec, std::chrono::milliseconds(500)));
  expect(relayed_book.source_sequence == 1U &&
         relayed_book.source_digest == sha256_hex(book().to_json()) &&
         relayed_book.canonical_payload == book().to_json(), "strategy book relay failed");
  const auto session_started = parse_ipc_envelope(read_ipc_frame(
      strategy, mode, codec, std::chrono::milliseconds(500)));
  expect(ExecutionEvent::parse(session_started.canonical_payload).event_type == "session_started" &&
             session.ready(), "session readiness was not gated by both peers and fresh book");
  send_ack(strategy, mode, codec, config.execution_session_id, *session_started.event_sequence);
  const IpcEnvelope order_packet{IpcMessageKind::OrderIntent, config.execution_session_id, "d51",
                                 std::nullopt, std::nullopt, intent().to_json(), std::nullopt};
  write_ipc_frame(strategy, mode, codec, encode_ipc_envelope(order_packet), std::chrono::milliseconds(500));
  std::uint64_t last_order_event = 0U;
  for (int index = 0; index < 5; ++index) {
    const auto event = parse_ipc_envelope(read_ipc_frame(
        strategy, mode, codec, std::chrono::milliseconds(500)));
    last_order_event = *event.event_sequence;
  }
  send_ack(strategy, mode, codec, config.execution_session_id, last_order_event);
  expect(broker.query_orders().items.size() == 1U, "paper place count invalid");
  auto modify_intent = intent();
  modify_intent.intent_id = "00000000-0000-4000-8000-000000000077";
  modify_intent.action = IntentAction::Modify;
  modify_intent.target_internal_order_id = broker.query_orders().items.front().internal_order_id;
  modify_intent.quantity = 65U;
  modify_intent.limit_price_paise = 1100U;
  const IpcEnvelope modify_packet{IpcMessageKind::OrderIntent, config.execution_session_id, "d51",
                                  std::nullopt, std::nullopt, modify_intent.to_json(), std::nullopt};
  write_ipc_frame(strategy, mode, codec, encode_ipc_envelope(modify_packet),
                  std::chrono::milliseconds(500));
  std::uint64_t last_modify_event = 0U;
  for (int index = 0; index < 5; ++index) {
    const auto event = parse_ipc_envelope(read_ipc_frame(
        strategy, mode, codec, std::chrono::milliseconds(500)));
    last_modify_event = *event.event_sequence;
  }
  send_ack(strategy, mode, codec, config.execution_session_id, last_modify_event);
  expect(broker.query_orders().items.front().limit_price_paise == 1100U,
         "paper modify did not establish the fill price used by recovery");
  clock.value.store(1100);
  auto partial_book = book(42U, 1050);
  const IpcEnvelope partial_packet{IpcMessageKind::StrategyBookObservation,
                                   config.execution_session_id, std::nullopt, std::nullopt,
                                   std::nullopt, partial_book.to_json(), std::nullopt};
  write_ipc_frame(market, mode, codec, encode_ipc_envelope(partial_packet),
                  std::chrono::milliseconds(500));
  const auto partial_market_evidence = ExecutionEvent::parse(parse_ipc_envelope(read_ipc_frame(
      strategy, mode, codec, std::chrono::milliseconds(500))).canonical_payload);
  expect(partial_market_evidence.event_type == "market_observation_accepted" &&
             json_uint64(partial_market_evidence.payload.at("source_sequence"),
                         "source_sequence") == 2U,
         "fill-triggering market evidence was not ordered before the fill");
  const auto fill_envelope = parse_ipc_envelope(read_ipc_frame(
      strategy, mode, codec, std::chrono::milliseconds(500)));
  const auto proxy_fill_event = ExecutionEvent::parse(fill_envelope.canonical_payload);
  expect(proxy_fill_event.event_type == "filled" &&
             json_uint64(proxy_fill_event.payload.at("cumulative_filled_quantity"),
                         "cumulative_filled_quantity") == 65U &&
             json_uint64(proxy_fill_event.payload.at("fill_price_paise"),
                         "fill_price_paise") == 1100U,
         "D51ProxyV1 did not preserve full-fill parity on a qualifying cross");
  const auto partial_relay = parse_ipc_envelope(read_ipc_frame(
      strategy, mode, codec, std::chrono::milliseconds(500)));
  expect(partial_relay.kind == IpcMessageKind::StrategyBookObservation &&
             partial_relay.source_sequence == 2U,
         "triggering book was not delivered after its prior-order fill event");
  send_ack(strategy, mode, codec, config.execution_session_id, *fill_envelope.event_sequence);
  clock.value.store(1200);
  auto full_book = book(75U, 1150);
  const IpcEnvelope full_packet{IpcMessageKind::StrategyBookObservation,
                                config.execution_session_id, std::nullopt, std::nullopt,
                                std::nullopt, full_book.to_json(), std::nullopt};
  write_ipc_frame(market, mode, codec, encode_ipc_envelope(full_packet),
                  std::chrono::milliseconds(500));
  const auto full_market_evidence = ExecutionEvent::parse(parse_ipc_envelope(read_ipc_frame(
      strategy, mode, codec, std::chrono::milliseconds(500))).canonical_payload);
  expect(full_market_evidence.event_type == "market_observation_accepted" &&
             json_uint64(full_market_evidence.payload.at("source_sequence"),
                         "source_sequence") == 3U,
         "terminal market evidence was not durable before relay");
  const auto full_relay = parse_ipc_envelope(read_ipc_frame(
      strategy, mode, codec, std::chrono::milliseconds(500)));
  expect(full_relay.kind == IpcMessageKind::StrategyBookObservation &&
             full_relay.source_sequence == 3U &&
             broker.query_positions().items.front().quantity == 65,
         "terminal proxy order produced a duplicate fill");
  const auto paper_pnl_before_restart = broker.query_pnl();
  expect(paper_pnl_before_restart.status == BrokerQueryStatus::Authoritative &&
             paper_pnl_before_restart.daily_loss_paise == 6825U,
         "modified-price pre-restart paper loss was not authoritative");
  for (std::size_t index = 0; index < static_cast<std::size_t>(ExecutorQueueKind::Count); ++index) {
    const auto metrics = executor.queue_metrics(static_cast<ExecutorQueueKind>(index));
    expect(metrics.high_water > 0U && metrics.high_water <= metrics.capacity,
           "production E2E did not traverse a configured bounded stage");
  }
  // Leave the last market-evidence event delivered but unacknowledged, then reconnect from the
  // older acknowledged cursor. Redelivery below the prior delivery high-water mark is legal.
  const auto acknowledged_cursor = *fill_envelope.event_sequence;
  (void)::close(strategy);
  strategy = connect_unix(server.strategy_socket_path(), mode);
  send_handshake(strategy, mode, codec, PeerRole::StrategyClient,
                 challenge_nonce(strategy, mode, codec), acknowledged_cursor);
  const auto durable_before_reconnect = audit.ledger().last_sequence();
  for (std::uint64_t sequence = acknowledged_cursor + 1U;
       sequence <= durable_before_reconnect; ++sequence) {
    const auto replayed = parse_ipc_envelope(read_ipc_frame(
        strategy, mode, codec, std::chrono::milliseconds(500)));
    expect(replayed.event_sequence == sequence, "reconnect did not redeliver from older ACK cursor");
  }
  expect(broker.query_orders().items.size() == 1U, "reconnect replay resubmitted intent");
  const auto reconnect_evidence =
      audit.ledger().verify(LedgerVerificationMode::RetainRecords);
  expect(!executor.safety_stopped() && !executor.safety_reason() && executor.ready() &&
             std::any_of(reconnect_evidence.records.begin(), reconnect_evidence.records.end(),
                         [](const LedgerRecord& record) {
                           const auto reason = record.event.payload.find("reason");
                           return record.event.event_type == "reconciliation_completed" &&
                                  reason != record.event.payload.end() &&
                                  json_string(reason->second, "reason") ==
                                      "strategy_reconnect_exact";
                         }),
         "strategy reconnect did not restore authority through durable exact reconciliation");
  auto simultaneous_intent = intent();
  simultaneous_intent.intent_id = "00000000-0000-4000-8000-000000000088";
  const IpcEnvelope simultaneous_order{IpcMessageKind::OrderIntent,
      config.execution_session_id, "d51", std::nullopt, std::nullopt,
      simultaneous_intent.to_json(), std::nullopt};
  write_ipc_frame(strategy, mode, codec, encode_ipc_envelope(simultaneous_order),
                  std::chrono::milliseconds(500));
  (void)::shutdown(market, SHUT_RDWR);
  (void)::close(market); market = -1;
  worker.join();
  expect(worker_error != nullptr && !executor.ready() && !executor.shutdown_succeeded() &&
             broker.query_orders().items.size() == 1U,
         "simultaneous market disconnect did not win before queued strategy broker work");
  const auto durable_after_shutdown = audit.ledger().last_sequence();
  const auto durable = verify_ledger(config.ledger_path, LedgerVerificationMode::RetainRecords);
  expect(durable.clean() && durable.records.size() == durable_after_shutdown,
         "single authoritative ledger record count invalid");
  const auto recovered_paper = recover_paper_broker(durable);
  PaperBroker restored(recovered_paper.snapshot);
  expect(restored.query_orders().items == broker.query_orders().items &&
             restored.query_trades().items == broker.query_trades().items &&
             restored.query_positions().items == broker.query_positions().items &&
             restored.query_pnl().status == BrokerQueryStatus::Authoritative &&
             restored.query_pnl().daily_loss_paise ==
                 paper_pnl_before_restart.daily_loss_paise &&
             restored.query_pnl().drawdown_paise ==
                 paper_pnl_before_restart.drawdown_paise &&
             restored.query_pnl().timestamp_ns == paper_pnl_before_restart.timestamp_ns,
         "production paper recovery did not reconstruct ledger state");
  (void)::close(strategy);
  expect(!std::filesystem::exists(runtime / "market.sock") &&
         !std::filesystem::exists(runtime / "strategy.sock"), "owned sockets survived shutdown");

  const auto clean_runtime = runtime / "clean-shutdown";
  std::filesystem::create_directory(clean_runtime);
  (void)::chmod(clean_runtime.c_str(), 0700);
  auto clean_config = config;
  clean_config.runtime_directory = clean_runtime;
  clean_config.ledger_path = clean_runtime / "events.ledger";
  PaperBroker clean_broker;
  auto clean_audit = ExecutionLedgerSessionAdapter::create_new(clean_config.ledger_path);
  ExecutionSession clean_session(clean_config.execution_session_id, RiskEngine(risk()), {},
                                 clean_audit, resolver, clean_broker, clock);
  expect(clean_session.preflight(), "clean-shutdown preflight failed");
  Executor clean_executor(clean_config, clean_session, clean_audit.ledger(), clock);
  ExecutorServer clean_server(clean_executor, clean_config, market_identity, strategy_identity,
                              market_inspector, strategy_inspector, false);
  std::exception_ptr clean_worker_error;
  std::thread clean_worker([&] {
    try { clean_server.run(); }
    catch (...) { clean_worker_error = std::current_exception(); }
  });
  int clean_market = connect_unix(clean_server.market_socket_path(), mode);
  send_handshake(clean_market, mode, codec, PeerRole::MarketPublisher,
                 challenge_nonce(clean_market, mode, codec));
  int clean_strategy = connect_unix(clean_server.strategy_socket_path(), mode);
  send_handshake(clean_strategy, mode, codec, PeerRole::StrategyClient,
                 challenge_nonce(clean_strategy, mode, codec));
  const auto clean_startup = parse_ipc_envelope(read_ipc_frame(
      clean_strategy, mode, codec, std::chrono::milliseconds(500)));
  send_ack(clean_strategy, mode, codec, clean_config.execution_session_id,
           *clean_startup.event_sequence);
  write_ipc_frame(clean_market, mode, codec, encode_ipc_envelope(market_packet),
                  std::chrono::milliseconds(500));
  std::uint64_t clean_ready_sequence = 0U;
  for (int index = 0; index < 3; ++index) {
    const auto item = parse_ipc_envelope(read_ipc_frame(
        clean_strategy, mode, codec, std::chrono::milliseconds(500)));
    if (item.event_sequence) clean_ready_sequence = *item.event_sequence;
  }
  send_ack(clean_strategy, mode, codec, clean_config.execution_session_id,
           clean_ready_sequence);
  clean_server.request_stop();
  bool saw_session_stopped = false;
  std::uint64_t clean_final_sequence = 0U;
  for (int index = 0; index < 8 && !saw_session_stopped; ++index) {
    const auto item = parse_ipc_envelope(read_ipc_frame(
        clean_strategy, mode, codec, std::chrono::milliseconds(500)));
    const auto event = ExecutionEvent::parse(item.canonical_payload);
    clean_final_sequence = *item.event_sequence;
    saw_session_stopped = event.event_type == "session_stopped";
  }
  expect(saw_session_stopped, "clean shutdown did not deliver session_stopped");
  send_ack(clean_strategy, mode, codec, clean_config.execution_session_id,
           clean_final_sequence);
  clean_worker.join();
  expect(clean_worker_error == nullptr && clean_executor.shutdown_succeeded() &&
             clean_executor.queue_metrics(ExecutorQueueKind::OutboundEvent).depth == 0U &&
             clean_final_sequence == clean_audit.ledger().last_sequence(),
         "clean shutdown did not receive a factual final-event ACK");
  (void)::close(clean_market);
  (void)::close(clean_strategy);

  const auto deadline_runtime = runtime / "absolute-deadline";
  std::filesystem::create_directory(deadline_runtime);
  (void)::chmod(deadline_runtime.c_str(), 0700);
  auto deadline_config = config;
  deadline_config.runtime_directory = deadline_runtime;
  deadline_config.ledger_path = deadline_runtime / "events.ledger";
  deadline_config.reconnect_window_ms = 40;
  PaperBroker deadline_broker;
  auto deadline_audit = ExecutionLedgerSessionAdapter::create_new(deadline_config.ledger_path);
  ExecutionSession deadline_session(deadline_config.execution_session_id, RiskEngine(risk()), {},
                                    deadline_audit, resolver, deadline_broker, clock);
  expect(deadline_session.preflight(), "absolute-auth-deadline preflight failed");
  Executor deadline_executor(deadline_config, deadline_session, deadline_audit.ledger(), clock);
  SlowInspector slow_market{evidence, std::chrono::milliseconds(70)};
  ExecutorServer deadline_server(deadline_executor, deadline_config, market_identity,
                                 strategy_identity, slow_market, strategy_inspector, false);
  std::exception_ptr deadline_error;
  const auto deadline_started = std::chrono::steady_clock::now();
  std::thread deadline_worker([&] {
    try { deadline_server.run(); }
    catch (...) { deadline_error = std::current_exception(); }
  });
  const int deadline_market = connect_unix(deadline_server.market_socket_path(), mode);
  send_handshake(deadline_market, mode, codec, PeerRole::MarketPublisher,
                 challenge_nonce(deadline_market, mode, codec));
  deadline_worker.join();
  const auto deadline_elapsed = std::chrono::steady_clock::now() - deadline_started;
  (void)::close(deadline_market);
  expect(deadline_error != nullptr && deadline_elapsed < std::chrono::milliseconds(180),
         "peer inspection renewed or escaped the absolute authentication deadline");
  std::filesystem::remove_all(runtime);
  return failures == 0 ? 0 : 1;
}
