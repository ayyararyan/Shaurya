#include "shaurya/execution/reconciliation.hpp"

#include <algorithm>
#include <map>
#include <set>
#include <string_view>

namespace shaurya::execution {
namespace {

bool allowed_order_state(std::string_view state) {
  return state == "working" || state == "acknowledged" || state == "partially_filled" ||
         state == "ambiguous" || state == "filled" || state == "cancelled" ||
         state == "rejected";
}

bool valid_provenance(std::string_view value) {
  return value == "simulated_proxy" || value == "sanitized_fixture" ||
         value == "broker_confirmed";
}

template <typename T, typename Key>
std::map<std::string, T> unique_map(const std::vector<T>& items, Key key,
                                    std::string_view duplicate_code,
                                    std::vector<std::string>& incidents) {
  std::map<std::string, T> output;
  for (const auto& item : items) {
    if (!output.emplace(key(item), item).second)
      incidents.emplace_back(duplicate_code);
  }
  return output;
}

template <typename T>
void compare_maps(const std::map<std::string, T>& replayed,
                  const std::map<std::string, T>& broker, std::string_view label,
                  std::vector<std::string>& incidents) {
  for (const auto& [key, value] : replayed) {
    const auto found = broker.find(key);
    if (found == broker.end()) incidents.push_back(std::string(label) + "_missing:" + key);
    else if (!(found->second == value)) incidents.push_back(std::string(label) + "_changed:" + key);
  }
  for (const auto& [key, unused] : broker) {
    (void)unused;
    if (!replayed.contains(key)) incidents.push_back(std::string(label) + "_extra:" + key);
  }
}

}  // namespace

ReconciliationResult Reconciler::compare(
    const ReplayedBrokerState& replayed,
    const BrokerQueryResult<BrokerOrderSnapshot>& broker_orders,
    const BrokerQueryResult<BrokerFillSnapshot>& broker_fills,
    const BrokerQueryResult<BrokerPositionSnapshot>& broker_positions,
    std::string execution_session_id, std::string snapshot_id,
    std::int64_t timestamp_ns) const {
  ReconciliationResult result;
  result.replayed = replayed;
  result.broker_orders = broker_orders;
  result.broker_fills = broker_fills;
  result.broker_positions = broker_positions;
  for (const auto pair : {std::pair{broker_orders.status, "orders"},
                          std::pair{broker_fills.status, "fills"},
                          std::pair{broker_positions.status, "positions"}}) {
    if (pair.first != BrokerQueryStatus::Authoritative)
      result.incidents.push_back(std::string(pair.second) + "_query_unavailable");
  }
  for (const auto& query_provenance : {broker_orders.provenance, broker_fills.provenance,
                                       broker_positions.provenance}) {
    if (!valid_provenance(query_provenance)) result.incidents.push_back("query_provenance_invalid");
  }
  const auto known = [&](std::string_view canonical) {
    return replayed.known_instruments.empty() || replayed.known_instruments.contains(std::string(canonical));
  };
  const auto validate_order = [&](const BrokerOrderSnapshot& order, std::string_view prefix) {
    if (!is_canonical_uuid(order.internal_order_id) ||
        !is_canonical_instrument_id(order.canonical_instrument_id) ||
        !known(order.canonical_instrument_id) || order.instrument_token.empty() ||
        order.quantity == 0U || order.cumulative_filled_quantity > order.quantity ||
        order.limit_price_paise == 0U || !allowed_order_state(order.state) ||
        !valid_provenance(order.provenance)) {
      result.incidents.push_back(std::string(prefix) + "_order_invalid");
    }
  };
  for (const auto& order : replayed.orders) validate_order(order, "replayed");
  for (const auto& order : broker_orders.items) validate_order(order, "broker");
  const auto validate_fill = [&](const BrokerFillSnapshot& fill, std::string_view prefix) {
    if (fill.fill_id.empty() || !is_canonical_uuid(fill.internal_order_id) ||
        !is_canonical_instrument_id(fill.canonical_instrument_id) ||
        !known(fill.canonical_instrument_id) || fill.instrument_token.empty() ||
        fill.last_fill_quantity == 0U ||
        fill.last_fill_quantity > fill.cumulative_filled_quantity ||
        fill.fill_price_paise == 0U || !valid_provenance(fill.provenance)) {
      result.incidents.push_back(std::string(prefix) + "_fill_invalid");
    }
  };
  for (const auto& fill : replayed.fills) validate_fill(fill, "replayed");
  for (const auto& fill : broker_fills.items) validate_fill(fill, "broker");
  const auto validate_position = [&](const BrokerPositionSnapshot& position,
                                     std::string_view prefix) {
    if (!is_canonical_instrument_id(position.canonical_instrument_id) ||
        !known(position.canonical_instrument_id) || position.instrument_token.empty() ||
        !valid_provenance(position.provenance)) {
      result.incidents.push_back(std::string(prefix) + "_position_invalid");
    }
  };
  for (const auto& position : replayed.positions) validate_position(position, "replayed");
  for (const auto& position : broker_positions.items) validate_position(position, "broker");

  auto replayed_orders = unique_map(replayed.orders,
      [](const BrokerOrderSnapshot& item) { return item.internal_order_id; },
      "replayed_order_duplicate", result.incidents);
  auto actual_orders = unique_map(broker_orders.items,
      [](const BrokerOrderSnapshot& item) { return item.internal_order_id; },
      "broker_order_duplicate", result.incidents);
  compare_maps(replayed_orders, actual_orders, "order", result.incidents);

  auto replayed_fills = unique_map(replayed.fills,
      [](const BrokerFillSnapshot& item) { return item.fill_id; },
      "replayed_fill_duplicate", result.incidents);
  auto actual_fills = unique_map(broker_fills.items,
      [](const BrokerFillSnapshot& item) { return item.fill_id; },
      "broker_fill_duplicate", result.incidents);
  compare_maps(replayed_fills, actual_fills, "fill", result.incidents);

  auto replayed_positions = unique_map(replayed.positions,
      [](const BrokerPositionSnapshot& item) { return item.canonical_instrument_id; },
      "replayed_position_duplicate", result.incidents);
  auto actual_positions = unique_map(broker_positions.items,
      [](const BrokerPositionSnapshot& item) { return item.canonical_instrument_id; },
      "broker_position_duplicate", result.incidents);
  compare_maps(replayed_positions, actual_positions, "position", result.incidents);

  std::set<std::string> instruments;
  for (const auto& [canonical, unused] : replayed.strategy_desired_positions) {
    (void)unused; instruments.insert(canonical);
  }
  for (const auto& [canonical, unused] : replayed_positions) {
    (void)unused; instruments.insert(canonical);
  }
  for (const auto& [canonical, unused] : actual_positions) {
    (void)unused; instruments.insert(canonical);
  }
  result.position_snapshot.snapshot_id = std::move(snapshot_id);
  result.position_snapshot.execution_session_id = std::move(execution_session_id);
  result.position_snapshot.timestamp_ns = timestamp_ns;
  result.position_snapshot.source = replayed.broker_source;
  result.position_snapshot.provenance = replayed.position_provenance;
  result.position_snapshot.reconciliation_status = result.incidents.empty() ? "matched" : "mismatch";
  for (const auto& canonical : instruments) {
    PositionEntry entry;
    entry.canonical_instrument_id = canonical;
    if (const auto found = actual_positions.find(canonical); found != actual_positions.end()) {
      entry.instrument_token = found->second.instrument_token;
      entry.broker_authoritative = found->second.quantity;
    } else if (const auto replayed_found = replayed_positions.find(canonical);
               replayed_found != replayed_positions.end()) {
      entry.instrument_token = replayed_found->second.instrument_token;
    } else {
      entry.instrument_token = "unknown";
    }
    if (const auto desired_found = replayed.strategy_desired_positions.find(canonical);
        desired_found != replayed.strategy_desired_positions.end())
      entry.strategy_desired = desired_found->second;
    if (const auto replayed_found = replayed_positions.find(canonical);
        replayed_found != replayed_positions.end())
      entry.ledger_reconstructed = replayed_found->second.quantity;
    result.position_snapshot.positions.push_back(std::move(entry));
  }
  result.exact_agreement = result.incidents.empty();
  result.safety_stop = !result.exact_agreement;
  try {
    (void)PositionSnapshot::parse(result.position_snapshot.to_json());
  } catch (const JsonError&) {
    result.incidents.push_back("position_snapshot_contract_invalid");
    result.exact_agreement = false;
    result.safety_stop = true;
    result.position_snapshot.reconciliation_status = "mismatch";
  }
  return result;
}

}  // namespace shaurya::execution
