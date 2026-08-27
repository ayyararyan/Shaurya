#include "shaurya/execution/kotak_adapter.hpp"

#include <iostream>
#include <fstream>
#include <iterator>

using namespace shaurya::execution;

int main() {
  int failures = 0;
  const auto expect = [&](bool condition, const char* message) {
    if (!condition) { std::cerr << message << '\n'; ++failures; }
  };
  BrokerOrderRequest request{"00000000-0000-4000-8000-000000000004", "intent",
      {"NSE:NSE_FNO:NIFTY:future:2026-08-27", "58072", "nse_fo", "NIFTY26AUGFUT", 65, 5},
      OrderSide::Buy, 65, 1000, 100, 0};
  const auto encoded = KotakFixtureCodec::build_place(request, "corr-1");
  expect(encoded.canonical_body.find("\"order_type\":\"LIMIT\"") != std::string::npos &&
             encoded.canonical_body.find("\"product\":\"NRML\"") != std::string::npos &&
             encoded.canonical_body.find("\"instrument_token\":\"58072\"") != std::string::npos,
         "place request contract");
  const auto ack = KotakFixtureCodec::parse_mutation_response(
      request.internal_order_id, "corr-1", 200,
      R"({"broker_correlation_id":"fixture-order-1","correlation_id":"corr-1","status":"acknowledged"})");
  expect(ack.status == BrokerMutationStatus::Acknowledged &&
             ack.provenance == "sanitized_fixture", "fixture ACK");
  {
    std::ifstream fixture(std::string(SHAURYA_EXECUTION_SOURCE_ROOT) +
                          "/tests/fixtures/kotak/place_ack.sanitized.json");
    const std::string body((std::istreambuf_iterator<char>(fixture)),
                           std::istreambuf_iterator<char>());
    expect(KotakFixtureCodec::parse_mutation_response(request.internal_order_id, "corr-1", 200,
                                                       body).status ==
               BrokerMutationStatus::Acknowledged,
           "Kotak fixture corpus not consumed");
  }
  const auto modified = KotakFixtureCodec::build_modify(
      {request.internal_order_id, 65, 1000}, request.route, OrderSide::Buy, "corr-2");
  const auto cancelled = KotakFixtureCodec::build_cancel(request.internal_order_id, request.route,
                                                         "corr-3");
  expect(modified.canonical_body.find("\"quantity\":65") != std::string::npos &&
             cancelled.canonical_body.find(request.internal_order_id) != std::string::npos,
         "modify/cancel fixture requests");
  const auto failed = KotakFixtureCodec::parse_mutation_response(
      request.internal_order_id, "corr-1", 503, "secret response body");
  expect(failed.error && failed.error->category == "http_failure" &&
             failed.error->correlation_id == "corr-1", "sanitized HTTP error");
  expect(!KotakFixtureCodec::live_transport_available(), "live transport exposed");
  try { KotakFixtureCodec::require_live_mode(true); expect(false, "live mode accepted"); }
  catch (const std::logic_error&) {}

  KotakFixtureUpdateQueue queue(1);
  const auto update = KotakFixtureCodec::parse_update(
      R"({"cumulative_filled_quantity":10,"internal_order_id":"00000000-0000-4000-8000-000000000004","sequence":1,"state":"partially_filled","update_id":"u1"})");
  expect(queue.push(update) && queue.push(update), "duplicate update not idempotent");
  auto second = update; second.sequence = 2; second.update_id = "u2";
  expect(!queue.push(second) && queue.safety_stopped(), "queue overflow did not stop");
  KotakFixtureUpdateQueue conflict_queue(4);
  expect(conflict_queue.push(update), "conflict setup");
  auto conflict = update; conflict.cumulative_filled_quantity = 11;
  expect(!conflict_queue.push(conflict) && conflict_queue.safety_stopped(),
         "conflicting duplicate update accepted");
  KotakFixtureUpdateQueue order_queue(4);
  auto newer = update; newer.sequence = 2; newer.update_id = "newer";
  expect(order_queue.push(newer) && !order_queue.push(update) && order_queue.safety_stopped(),
         "out-of-order update accepted");
  const auto lost = KotakFixtureCodec::parse_update(
      R"({"cumulative_filled_quantity":0,"internal_order_id":"","sequence":3,"state":"session_lost","update_id":"lost-1"})");
  KotakFixtureUpdateQueue loss_queue(4);
  expect(!loss_queue.push(lost) && loss_queue.safety_stopped(), "session loss accepted");
  const auto malformed = KotakFixtureCodec::parse_mutation_response(
      request.internal_order_id, "corr-1", 200, "{bad");
  expect(malformed.status == BrokerMutationStatus::Ambiguous && malformed.error &&
             malformed.error->category == "malformed_response", "malformed response not ambiguous");
  return failures == 0 ? 0 : 1;
}
