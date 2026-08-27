#include "shaurya/execution/canonical_json.hpp"
#include "shaurya/execution/ipc_protocol.hpp"

#include <iostream>

using namespace shaurya::execution;

namespace {
template <typename Function> bool refused(Function action) {
  try { action(); } catch (const IpcProtocolError&) { return true; }
  return false;
}
StrategyBookObservation book() {
  StrategyBookObservation value;
  value.canonical_instrument_id = "NSE:NSE_FNO:NIFTY:future:2026-08-27";
  value.bids = {{995, 100, 5}, {990, 90, 4}, {985, 80, 3}, {980, 70, 2}, {975, 60, 1}};
  value.asks = {{1000, 110, 6}, {1005, 120, 7}, {1010, 130, 8}, {1015, 140, 9},
                {1020, 150, 10}};
  value.last_trade_paise = 998; value.cumulative_volume = 10;
  value.last_trade_quantity = 2; value.open_interest = 500;
  value.exchange_timestamp_ns = 940; value.receive_timestamp_ns = 950;
  value.source = "dhan"; value.provenance = "observed";
  return value;
}
std::string mutate_book(const StrategyBookObservation& value, const std::string& field,
                        JsonValue replacement) {
  auto document = parse_json(value.to_json());
  auto& object = std::get<JsonObject>(document.value);
  object[field] = std::move(replacement);
  return canonical_json(document);
}
std::string remove_book_field(const StrategyBookObservation& value, const std::string& field) {
  auto document = parse_json(value.to_json());
  auto& object = std::get<JsonObject>(document.value);
  object.erase(field);
  return canonical_json(document);
}
ExecutionEvent event(std::string id) {
  ExecutionEvent value;
  value.event_id = std::move(id); value.event_type = "session_started"; value.timestamp_ns = 1000;
  value.execution_session_id = "00000000-0000-4000-8000-000000000003";
  value.payload = {};
  return value;
}
}

int main() {
  int failures = 0;
  const auto expect = [&](bool value, const char* message) {
    if (!value) { std::cerr << message << '\n'; ++failures; }
  };
  const std::string handshake_raw =
    "{\"configuration_digest\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\","
    "\"execution_session_id\":\"00000000-0000-4000-8000-000000000003\","
    "\"executable_digest\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\","
    "\"nonce\":\"fresh\",\"process_start_identity\":\"start\",\"protocol_version\":\"1.0.0\","
    "\"role\":\"strategy_client\",\"schema_version\":\"1.0.0\",\"strategy_id\":\"d51\"}";
  const std::string handshake = canonical_json(parse_json(handshake_raw));
  expect(parse_ipc_handshake(handshake).strategy_id == "d51", "handshake rejected");
  expect(refused([&] { (void)parse_ipc_handshake(" " + handshake); }),
         "noncanonical handshake accepted");
  expect(refused([&] { (void)parse_ipc_handshake(handshake.substr(0, handshake.size() - 1U) +
                                                 ",\"unknown\":1}"); }), "unknown field accepted");
  const auto original_book = book();
  expect(StrategyBookObservation::parse(original_book.to_json()) == original_book,
         "strategy book did not round trip");
  const auto aggregate = original_book.derive_market_observation();
  expect(aggregate.best_bid_paise == 995U && aggregate.best_ask_paise == 1000U &&
         aggregate.last_trade_paise == 998U && aggregate.cumulative_volume == 10U &&
         aggregate.receive_timestamp_ns == 950, "aggregate derivation changed source facts");
  expect(refused([&] {
    (void)StrategyBookObservation::parse(remove_book_field(original_book, "open_interest"));
  }), "missing D51 open interest accepted");
  expect(refused([&] {
    (void)StrategyBookObservation::parse(
        mutate_book(original_book, "bid_count", JsonValue(JsonInteger{"4"})));
  }), "depth count mismatch accepted");
  auto unordered = original_book;
  unordered.bids[1].price_paise = unordered.bids[0].price_paise;
  expect(refused([&] { (void)StrategyBookObservation::parse(unordered.to_json()); }),
         "unordered bid levels accepted");
  auto zero_quantity = original_book;
  zero_quantity.asks[0].quantity = 0;
  expect(refused([&] { (void)StrategyBookObservation::parse(zero_quantity.to_json()); }),
         "zero displayed quantity accepted");

  const IpcEnvelope market{IpcMessageKind::StrategyBookObservation,
    "00000000-0000-4000-8000-000000000003", std::nullopt, std::nullopt, std::nullopt,
    original_book.to_json(), std::nullopt};
  const auto decoded = parse_ipc_envelope(encode_ipc_envelope(market));
  authorize_inbound(PeerRole::MarketPublisher, decoded, market.execution_session_id, "d51");
  expect(!decoded.source_sequence && !decoded.source_digest,
         "publisher supplied executor-owned correlation");
  expect(refused([&] { authorize_inbound(PeerRole::StrategyClient, decoded,
                                         market.execution_session_id, "d51"); }),
         "strategy injected market data");
  const EventAcknowledgement acknowledgement{2U};
  expect(EventAcknowledgement::parse(acknowledgement.to_json()) == acknowledgement,
         "closed acknowledgement did not round trip");
  const IpcEnvelope acknowledged{IpcMessageKind::EventAcknowledgement,
    market.execution_session_id, "d51", std::nullopt, 2U, acknowledgement.to_json(), std::nullopt};
  authorize_inbound(PeerRole::StrategyClient,
                    parse_ipc_envelope(encode_ipc_envelope(acknowledged)),
                    market.execution_session_id, "d51");
  auto mismatched_ack = acknowledged;
  mismatched_ack.event_sequence = 1U;
  expect(refused([&] { (void)parse_ipc_envelope(encode_ipc_envelope(mismatched_ack)); }),
         "acknowledgement envelope/payload mismatch accepted");
  auto unknown_ack = parse_json(acknowledgement.to_json());
  std::get<JsonObject>(unknown_ack.value).emplace("unknown", JsonValue(std::string("x")));
  expect(refused([&] { (void)EventAcknowledgement::parse(canonical_json(unknown_ack)); }),
         "acknowledgement unknown field accepted");
  const IpcEnvelope relayed{IpcMessageKind::StrategyBookObservation,
    market.execution_session_id, std::nullopt, 1U, std::nullopt, original_book.to_json(),
    sha256_hex(original_book.to_json())};
  const auto relayed_decoded = parse_ipc_envelope(encode_ipc_envelope(relayed));
  expect(relayed_decoded.source_sequence == 1U &&
         relayed_decoded.source_digest == sha256_hex(original_book.to_json()),
         "executor correlation not preserved");
  auto digest_without_sequence = relayed;
  digest_without_sequence.source_sequence.reset();
  expect(refused([&] { (void)parse_ipc_envelope(encode_ipc_envelope(digest_without_sequence)); }),
         "unpaired source digest accepted");
  auto wrong_digest = relayed;
  wrong_digest.source_digest = std::string(64U, '0');
  expect(refused([&] { (void)parse_ipc_envelope(encode_ipc_envelope(wrong_digest)); }),
         "source digest not bound to canonical strategy book");
  const IpcEnvelope legacy{IpcMessageKind::MarketObservation, market.execution_session_id,
                           std::nullopt, 1U, std::nullopt,
                           original_book.derive_market_observation().to_json(), std::nullopt};
  expect(refused([&] { authorize_inbound(PeerRole::MarketPublisher, legacy,
                                         market.execution_session_id, "d51"); }),
         "legacy aggregate publisher input accepted");

  EventReplayLog replay;
  replay.append({1U, market.execution_session_id, "d51",
                 event("00000000-0000-4000-8000-000000000011").to_json()});
  replay.append({2U, market.execution_session_id, "d51",
                 event("00000000-0000-4000-8000-000000000012").to_json()});
  expect(replay.replay_after(0U, market.execution_session_id, "d51").size() == 2U,
         "event replay incomplete");
  expect(refused([&] { (void)replay.replay_after(3U, market.execution_session_id, "d51"); }),
         "future cursor accepted");
  expect(refused([&] { (void)replay.replay_after(0U, market.execution_session_id, "other"); }),
         "cross-strategy replay accepted");
  return failures == 0 ? 0 : 1;
}
