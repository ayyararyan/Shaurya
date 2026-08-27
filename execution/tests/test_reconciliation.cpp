#include "shaurya/execution/reconciliation.hpp"

#include <iostream>

using namespace shaurya::execution;

int main() {
  int failures = 0;
  const auto expect = [&](bool condition, const char* message) {
    if (!condition) { std::cerr << message << '\n'; ++failures; }
  };
  ReplayedBrokerState replayed;
  replayed.positions.push_back({"NSE:NSE_FNO:NIFTY:future:2026-08-27", "58072", 65,
                                "simulated_proxy"});
  replayed.strategy_desired_positions.emplace("NSE:NSE_FNO:NIFTY:future:2026-08-27", 130);
  replayed.known_instruments.insert("NSE:NSE_FNO:NIFTY:future:2026-08-27");
  BrokerQueryResult<BrokerOrderSnapshot> orders{BrokerQueryStatus::Authoritative, {}, "simulated_proxy"};
  BrokerQueryResult<BrokerFillSnapshot> fills{BrokerQueryStatus::Authoritative, {}, "simulated_proxy"};
  BrokerQueryResult<BrokerPositionSnapshot> positions{
      BrokerQueryStatus::Authoritative, replayed.positions, "simulated_proxy"};
  const Reconciler reconciler;
  const auto exact = reconciler.compare(replayed, orders, fills, positions,
      "00000000-0000-4000-8000-000000000003",
      "00000000-0000-4000-8000-000000000031", 100);
  expect(exact.exact_agreement && !exact.safety_stop, "exact reconciliation failed");
  const auto& entry = exact.position_snapshot.positions.front();
  expect(entry.strategy_desired == 130 && entry.ledger_reconstructed == 65 &&
             entry.broker_authoritative == 65, "position meanings collapsed");
  expect(PositionSnapshot::parse(exact.position_snapshot.to_json()) == exact.position_snapshot,
         "position snapshot violates frozen contract");

  positions.items.front().quantity = 64;
  const auto changed = reconciler.compare(replayed, orders, fills, positions,
      "00000000-0000-4000-8000-000000000003",
      "00000000-0000-4000-8000-000000000032", 101);
  expect(!changed.exact_agreement && changed.safety_stop &&
             !changed.incidents.empty(), "position mismatch accepted");
  positions.status = BrokerQueryStatus::Unavailable; positions.items.clear();
  const auto unavailable = reconciler.compare(replayed, orders, fills, positions,
      "00000000-0000-4000-8000-000000000003",
      "00000000-0000-4000-8000-000000000033", 102);
  expect(!unavailable.exact_agreement, "unavailable query treated as empty");

  BrokerOrderSnapshot order{"00000000-0000-4000-8000-000000000004",
      "NSE:NSE_FNO:NIFTY:future:2026-08-27", "58072", OrderSide::Buy, 65, 1000, 0,
      "working", "simulated_proxy"};
  replayed.orders = {order};
  orders.items = {order};
  positions.status = BrokerQueryStatus::Authoritative;
  positions.items = replayed.positions;
  auto order_exact = reconciler.compare(replayed, orders, fills, positions,
      "00000000-0000-4000-8000-000000000003",
      "00000000-0000-4000-8000-000000000034", 103);
  expect(order_exact.exact_agreement, "exact order set mismatched");
  orders.items.clear();
  expect(!reconciler.compare(replayed, orders, fills, positions,
      "00000000-0000-4000-8000-000000000003",
      "00000000-0000-4000-8000-000000000035", 104).exact_agreement,
      "missing broker order accepted");
  orders.items = {order, order};
  expect(!reconciler.compare(replayed, orders, fills, positions,
      "00000000-0000-4000-8000-000000000003",
      "00000000-0000-4000-8000-000000000036", 105).exact_agreement,
      "duplicate broker order accepted");
  auto unknown = order; unknown.internal_order_id = "00000000-0000-4000-8000-000000000005";
  unknown.canonical_instrument_id = "NSE:NSE_FNO:BANKNIFTY:future:2026-08-27";
  orders.items = {order, unknown};
  expect(!reconciler.compare(replayed, orders, fills, positions,
      "00000000-0000-4000-8000-000000000003",
      "00000000-0000-4000-8000-000000000037", 106).exact_agreement,
      "unknown instrument accepted");
  orders.items = replayed.orders;
  BrokerFillSnapshot fill{"fill-1", order.internal_order_id,
      order.canonical_instrument_id, order.instrument_token, 10, 10, 1000, 107,
      "simulated_proxy"};
  replayed.fills = {fill}; fills.items = {fill};
  expect(reconciler.compare(replayed, orders, fills, positions,
      "00000000-0000-4000-8000-000000000003",
      "00000000-0000-4000-8000-000000000038", 107).exact_agreement,
      "exact fill set mismatched");
  fills.items.front().cumulative_filled_quantity = 11;
  expect(!reconciler.compare(replayed, orders, fills, positions,
      "00000000-0000-4000-8000-000000000003",
      "00000000-0000-4000-8000-000000000039", 108).exact_agreement,
      "changed fill accepted");
  return failures == 0 ? 0 : 1;
}
