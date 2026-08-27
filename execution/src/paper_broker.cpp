#include "shaurya/execution/paper_broker.hpp"

#include <algorithm>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace shaurya::execution {
namespace {
constexpr std::string_view kPaperProvenance = "simulated_proxy";
bool terminal(std::string_view state) {
  return state == "filled" || state == "cancelled" || state == "rejected";
}

bool checked_add(std::int64_t left, std::int64_t right, std::int64_t& result) {
  if ((right > 0 && left > std::numeric_limits<std::int64_t>::max() - right) ||
      (right < 0 && left < std::numeric_limits<std::int64_t>::min() - right)) return false;
  result = left + right;
  return true;
}

bool checked_notional(std::uint64_t quantity, std::uint64_t price,
                      std::int64_t& result) {
  if (quantity > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) ||
      (quantity != 0U && price > static_cast<std::uint64_t>(
          std::numeric_limits<std::int64_t>::max()) / quantity)) return false;
  result = static_cast<std::int64_t>(quantity * price);
  return true;
}
}

PaperBroker::PaperBroker(PaperFillModel model, bool fixture_script_authorized) : model_(model) {
  if (model == PaperFillModel::ScriptedV1 && !fixture_script_authorized)
    throw std::invalid_argument("scripted_model_fixture_only");
}

PaperBroker::PaperBroker(PaperBrokerSnapshot snapshot, bool fixture_script_authorized)
    : model_(snapshot.model), health_(snapshot.health), sequence_(snapshot.sequence),
      cash_paise_(snapshot.cash_paise), peak_equity_paise_(snapshot.peak_equity_paise),
      latest_observation_ns_(snapshot.latest_observation_ns), pnl_valid_(snapshot.pnl_valid) {
  if (model_ == PaperFillModel::ScriptedV1 && !fixture_script_authorized)
    throw std::invalid_argument("scripted_model_fixture_only");
  if (snapshot.requests.size() != snapshot.orders.size())
    throw std::invalid_argument("paper_snapshot_shape_mismatch");
  for (std::size_t index = 0; index < snapshot.orders.size(); ++index) {
    const auto& request = snapshot.requests[index];
    const auto& order = snapshot.orders[index];
    if (request.internal_order_id != order.internal_order_id || request.quantity != order.quantity ||
        request.route.canonical_instrument_id != order.canonical_instrument_id ||
        request.route.instrument_token != order.instrument_token ||
        order.cumulative_filled_quantity > order.quantity ||
        !orders_.emplace(order.internal_order_id,
                         PaperOrder{request, order, request.baseline_cumulative_volume, false,
                                    !terminal(order.state)}).second) {
      throw std::invalid_argument("paper_snapshot_invalid_order");
    }
  }
  fills_ = std::move(snapshot.fills);
  for (const auto& position : snapshot.positions) {
    if (!positions_.emplace(position.canonical_instrument_id, position.quantity).second)
      throw std::invalid_argument("paper_snapshot_duplicate_position");
  }
  for (auto& mark : snapshot.marks) {
    if (mark.canonical_instrument_id.empty() || mark.timestamp_ns < 0 ||
        !marks_.emplace(mark.canonical_instrument_id, std::move(mark)).second)
      throw std::invalid_argument("paper_snapshot_invalid_mark");
  }
  if (peak_equity_paise_ < 0)
    throw std::invalid_argument("paper_snapshot_negative_peak_equity");
  const auto equity = equity_paise();
  if (pnl_valid_ && equity && peak_equity_paise_ < *equity)
    throw std::invalid_argument("paper_snapshot_invalid_peak_equity");
}

std::string PaperBroker::next_correlation_id() {
  std::ostringstream value;
  value << "paper-" << std::setw(8) << std::setfill('0') << ++sequence_;
  return value.str();
}

BrokerMutationResult PaperBroker::place(const BrokerOrderRequest& request) {
  if (health_ != BrokerSessionHealth::Ready)
    return {BrokerMutationStatus::Ambiguous, request.internal_order_id, std::nullopt,
            std::string(kPaperProvenance), BrokerError{"paper_session_unavailable", std::nullopt,
                                                       next_correlation_id()}};
  if (request.internal_order_id.empty() || request.quantity == 0U ||
      request.quantity > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) ||
      request.limit_price_paise == 0U || request.route.canonical_instrument_id.empty() ||
      orders_.contains(request.internal_order_id))
    return {BrokerMutationStatus::Rejected, request.internal_order_id, std::nullopt,
            std::string(kPaperProvenance), BrokerError{"paper_place_rejected", std::nullopt,
                                                       next_correlation_id()}};
  const auto correlation = next_correlation_id();
  BrokerOrderSnapshot snapshot{request.internal_order_id,
                               request.route.canonical_instrument_id,
                               request.route.instrument_token,
                               request.side,
                               request.quantity,
                               request.limit_price_paise,
                               0U,
                               "working",
                               std::string(kPaperProvenance)};
  orders_.emplace(request.internal_order_id,
                  PaperOrder{request, std::move(snapshot), request.baseline_cumulative_volume,
                             false, false});
  return {BrokerMutationStatus::Acknowledged, request.internal_order_id, correlation,
          std::string(kPaperProvenance), std::nullopt};
}

BrokerMutationResult PaperBroker::modify(const BrokerModifyRequest& request) {
  if (health_ != BrokerSessionHealth::Ready)
    return {BrokerMutationStatus::Ambiguous, request.internal_order_id, std::nullopt,
            std::string(kPaperProvenance), BrokerError{"paper_session_unavailable", std::nullopt,
                                                       next_correlation_id()}};
  const auto iterator = orders_.find(request.internal_order_id);
  if (iterator == orders_.end() || terminal(iterator->second.snapshot.state) ||
      request.quantity < iterator->second.snapshot.cumulative_filled_quantity ||
      request.quantity == 0U ||
      request.quantity > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) ||
      request.limit_price_paise == 0U)
    return {BrokerMutationStatus::Rejected, request.internal_order_id, std::nullopt,
            std::string(kPaperProvenance), BrokerError{"paper_modify_rejected", std::nullopt,
                                                       next_correlation_id()}};
  iterator->second.request.quantity = request.quantity;
  iterator->second.request.limit_price_paise = request.limit_price_paise;
  iterator->second.snapshot.quantity = request.quantity;
  iterator->second.snapshot.limit_price_paise = request.limit_price_paise;
  return {BrokerMutationStatus::Acknowledged, request.internal_order_id, next_correlation_id(),
          std::string(kPaperProvenance), std::nullopt, false, request.quantity,
          request.limit_price_paise};
}

BrokerMutationResult PaperBroker::cancel(std::string_view internal_order_id) {
  if (health_ != BrokerSessionHealth::Ready)
    return {BrokerMutationStatus::Ambiguous, std::string(internal_order_id), std::nullopt,
            std::string(kPaperProvenance), BrokerError{"paper_session_unavailable", std::nullopt,
                                                       next_correlation_id()}};
  const auto iterator = orders_.find(std::string(internal_order_id));
  if (iterator == orders_.end())
    return {BrokerMutationStatus::Rejected, std::string(internal_order_id), std::nullopt,
            std::string(kPaperProvenance), BrokerError{"paper_unknown_target", std::nullopt,
                                                       next_correlation_id()}};
  if (iterator->second.snapshot.state == "cancelled")
    return {BrokerMutationStatus::Acknowledged, std::string(internal_order_id),
            next_correlation_id(), std::string(kPaperProvenance), std::nullopt, true};
  if (terminal(iterator->second.snapshot.state))
    return {BrokerMutationStatus::Rejected, std::string(internal_order_id), std::nullopt,
            std::string(kPaperProvenance), BrokerError{"paper_terminal_target", std::nullopt,
                                                       next_correlation_id()}};
  iterator->second.snapshot.state = "cancelled";
  return {BrokerMutationStatus::Acknowledged, std::string(internal_order_id), next_correlation_id(),
          std::string(kPaperProvenance), std::nullopt, true};
}

BrokerFillSnapshot PaperBroker::fill(PaperOrder& order, std::uint64_t cumulative,
                                     std::int64_t timestamp_ns) {
  const std::uint64_t previous = order.snapshot.cumulative_filled_quantity;
  cumulative = std::min(cumulative, order.snapshot.quantity);
  BrokerFillSnapshot result{next_correlation_id(), order.snapshot.internal_order_id,
                            order.snapshot.canonical_instrument_id, order.snapshot.instrument_token,
                            cumulative, cumulative - previous, order.snapshot.limit_price_paise,
                            timestamp_ns, std::string(kPaperProvenance)};
  order.snapshot.cumulative_filled_quantity = cumulative;
  order.snapshot.state = cumulative == order.snapshot.quantity ? "filled" : "partially_filled";
  const auto signed_fill = static_cast<std::int64_t>(result.last_fill_quantity);
  auto& position = positions_[order.snapshot.canonical_instrument_id];
  std::int64_t updated_position{};
  std::int64_t notional{};
  const auto signed_position_change = order.snapshot.side == OrderSide::Buy
                                          ? signed_fill : -signed_fill;
  const auto signed_cash_change = order.snapshot.side == OrderSide::Buy
                                      ? -1 : 1;
  if (!checked_add(position, signed_position_change, updated_position)) {
    health_ = BrokerSessionHealth::Lost;
    pnl_valid_ = false;
  } else {
    position = updated_position;
    if (!checked_notional(result.last_fill_quantity, result.fill_price_paise, notional) ||
        !checked_add(cash_paise_, signed_cash_change * notional, cash_paise_))
      pnl_valid_ = false;
  }
  fills_.push_back(result);
  update_peak_equity();
  return result;
}

std::optional<std::int64_t> PaperBroker::equity_paise() const noexcept {
  if (!pnl_valid_) return std::nullopt;
  std::int64_t equity = cash_paise_;
  for (const auto& [canonical, quantity] : positions_) {
    if (quantity == 0) continue;
    const auto found = marks_.find(canonical);
    if (found == marks_.end()) return std::nullopt;
    const auto& mark = found->second;
    const auto price = quantity > 0
        ? mark.best_bid_paise.value_or(mark.last_trade_paise.value_or(0U))
        : mark.best_ask_paise.value_or(mark.last_trade_paise.value_or(0U));
    if (price == 0U) return std::nullopt;
    const auto absolute_quantity = quantity == std::numeric_limits<std::int64_t>::min()
        ? std::numeric_limits<std::uint64_t>::max()
        : static_cast<std::uint64_t>(quantity < 0 ? -quantity : quantity);
    std::int64_t notional{};
    std::int64_t updated{};
    if (!checked_notional(absolute_quantity, price, notional) ||
        !checked_add(equity, quantity > 0 ? notional : -notional, updated)) return std::nullopt;
    equity = updated;
  }
  return equity;
}

void PaperBroker::update_peak_equity() noexcept {
  const auto equity = equity_paise();
  if (equity) peak_equity_paise_ = std::max(peak_equity_paise_, *equity);
}

std::vector<BrokerFillSnapshot> PaperBroker::accept_observation(
    const MarketObservation& observation) {
  std::vector<BrokerFillSnapshot> generated;
  if (health_ != BrokerSessionHealth::Ready ||
      observation.source != "dhan" || observation.provenance != "observed" ||
      observation.receive_timestamp_ns < 0 ||
      (observation.exchange_timestamp_ns &&
       (*observation.exchange_timestamp_ns < 0 ||
        *observation.exchange_timestamp_ns > observation.receive_timestamp_ns)) ||
      (observation.best_bid_paise && observation.best_ask_paise &&
       *observation.best_bid_paise > *observation.best_ask_paise) ||
      std::find(observation.quality_flags.begin(), observation.quality_flags.end(), "unusable") !=
          observation.quality_flags.end() ||
      std::find(observation.quality_flags.begin(), observation.quality_flags.end(), "stale") !=
          observation.quality_flags.end() ||
      std::find(observation.quality_flags.begin(), observation.quality_flags.end(), "crossed_book") !=
      observation.quality_flags.end()) return generated;
  latest_observation_ns_ = std::max(latest_observation_ns_, observation.receive_timestamp_ns);
  const auto existing_mark = marks_.find(observation.canonical_instrument_id);
  if (existing_mark == marks_.end() ||
      observation.receive_timestamp_ns >= existing_mark->second.timestamp_ns) {
    marks_[observation.canonical_instrument_id] = {
        observation.canonical_instrument_id, observation.best_bid_paise,
        observation.best_ask_paise, observation.last_trade_paise,
        observation.receive_timestamp_ns};
  }
  if (model_ != PaperFillModel::D51ProxyV1) {
    update_peak_equity();
    return generated;
  }
  for (auto& [unused, order] : orders_) {
    (void)unused;
    if (terminal(order.snapshot.state) ||
        order.snapshot.canonical_instrument_id != observation.canonical_instrument_id ||
        observation.receive_timestamp_ns <= order.request.submitted_at_ns ||
        (observation.exchange_timestamp_ns &&
         (*observation.exchange_timestamp_ns <= order.request.submitted_at_ns ||
          *observation.exchange_timestamp_ns > observation.receive_timestamp_ns))) continue;
    if (order.awaiting_restart_baseline) {
      order.observed_cumulative_volume = observation.cumulative_volume;
      order.volume_reset = false;
      order.awaiting_restart_baseline = false;
      continue;
    }
    if (observation.cumulative_volume < order.observed_cumulative_volume) {
      order.observed_cumulative_volume = observation.cumulative_volume;
      order.volume_reset = true;
      continue;
    }
    const auto previous_volume = order.observed_cumulative_volume;
    const bool volume_advanced = observation.cumulative_volume > previous_volume;
    order.volume_reset = false;
    order.observed_cumulative_volume = observation.cumulative_volume;
    const bool quote_crossed = order.snapshot.side == OrderSide::Buy
                                   ? observation.best_ask_paise &&
                                         *observation.best_ask_paise <= order.snapshot.limit_price_paise
                                   : observation.best_bid_paise &&
                                         *observation.best_bid_paise >= order.snapshot.limit_price_paise;
    const bool trade_crossed = volume_advanced && observation.last_trade_paise &&
                               (order.snapshot.side == OrderSide::Buy
                                    ? *observation.last_trade_paise <= order.snapshot.limit_price_paise
                                    : *observation.last_trade_paise >= order.snapshot.limit_price_paise);
    if ((quote_crossed || trade_crossed) && volume_advanced) {
      const auto remaining = order.snapshot.quantity - order.snapshot.cumulative_filled_quantity;
      if (remaining > 0U)
        generated.push_back(fill(order, order.snapshot.quantity,
                                 observation.receive_timestamp_ns));
    }
  }
  update_peak_equity();
  return generated;
}

std::vector<BrokerFillSnapshot> PaperBroker::apply_scripted(
    const std::vector<ScriptedPaperEvent>& events) {
  if (model_ != PaperFillModel::ScriptedV1) throw std::logic_error("scripted_model_not_enabled");
  std::vector<BrokerFillSnapshot> generated;
  for (const auto& event : events) {
    if (event.update_id.empty() || event.update_id.size() > 64U ||
        event.internal_order_id.empty() || event.timestamp_ns < 0) {
      throw std::invalid_argument("invalid_scripted_paper_event");
    }
    if (std::find(applied_script_updates_.begin(), applied_script_updates_.end(), event.update_id) !=
        applied_script_updates_.end()) continue;
    applied_script_updates_.push_back(event.update_id);
    if (event.kind == ScriptedPaperEventKind::SessionLoss) { health_ = BrokerSessionHealth::Lost; continue; }
    const auto iterator = orders_.find(event.internal_order_id);
    if (iterator == orders_.end()) continue;
    auto& order = iterator->second;
    if (event.kind == ScriptedPaperEventKind::Reject && !terminal(order.snapshot.state)) {
      order.snapshot.state = "rejected";
    } else if (event.kind == ScriptedPaperEventKind::Ambiguous && !terminal(order.snapshot.state)) {
      order.snapshot.state = "ambiguous";
      health_ = BrokerSessionHealth::Unknown;
    } else if (!terminal(order.snapshot.state) &&
               event.cumulative_filled_quantity > order.snapshot.quantity) {
      throw std::invalid_argument("scripted_fill_exceeds_quantity");
    } else if (!terminal(order.snapshot.state) &&
               event.cumulative_filled_quantity > order.snapshot.cumulative_filled_quantity) {
      generated.push_back(fill(order, event.cumulative_filled_quantity, event.timestamp_ns));
    }
  }
  return generated;
}

BrokerQueryResult<BrokerOrderSnapshot> PaperBroker::query_orders() const {
  std::vector<BrokerOrderSnapshot> items;
  for (const auto& [unused, order] : orders_) { (void)unused; items.push_back(order.snapshot); }
  return {health_ == BrokerSessionHealth::Lost ? BrokerQueryStatus::Unavailable
                                               : BrokerQueryStatus::Authoritative,
          std::move(items), std::string(kPaperProvenance)};
}

BrokerQueryResult<BrokerFillSnapshot> PaperBroker::query_trades() const {
  return {health_ == BrokerSessionHealth::Lost ? BrokerQueryStatus::Unavailable
                                               : BrokerQueryStatus::Authoritative,
          fills_, std::string(kPaperProvenance)};
}

BrokerQueryResult<BrokerPositionSnapshot> PaperBroker::query_positions() const {
  std::vector<BrokerPositionSnapshot> items;
  for (const auto& [canonical, quantity] : positions_) {
    const auto order = std::find_if(orders_.begin(), orders_.end(), [&](const auto& item) {
      return item.second.snapshot.canonical_instrument_id == canonical;
    });
    items.push_back({canonical, order == orders_.end() ? "" : order->second.snapshot.instrument_token,
                     quantity, std::string(kPaperProvenance)});
  }
  return {health_ == BrokerSessionHealth::Lost ? BrokerQueryStatus::Unavailable
                                               : BrokerQueryStatus::Authoritative,
          std::move(items), std::string(kPaperProvenance)};
}

BrokerPnlSnapshot PaperBroker::query_pnl() const {
  if (health_ != BrokerSessionHealth::Ready || latest_observation_ns_ <= 0)
    return {};
  const auto equity = equity_paise();
  if (!equity || peak_equity_paise_ < *equity) return {};
  const auto loss = *equity < 0 ? static_cast<std::uint64_t>(-(*equity + 1)) + 1U : 0U;
  std::uint64_t drawdown{};
  const auto peak = static_cast<std::uint64_t>(peak_equity_paise_);
  if (*equity >= 0) {
    const auto positive_equity = static_cast<std::uint64_t>(*equity);
    if (positive_equity > peak) return {};
    drawdown = peak - positive_equity;
  } else {
    const auto absolute_equity = static_cast<std::uint64_t>(-(*equity + 1)) + 1U;
    if (peak > std::numeric_limits<std::uint64_t>::max() - absolute_equity) return {};
    drawdown = peak + absolute_equity;
  }
  std::int64_t evidence_timestamp = latest_observation_ns_;
  for (const auto& [canonical, quantity] : positions_) {
    if (quantity == 0) continue;
    const auto mark = marks_.find(canonical);
    if (mark == marks_.end()) return {};
    evidence_timestamp = std::min(evidence_timestamp, mark->second.timestamp_ns);
  }
  return {BrokerQueryStatus::Authoritative, evidence_timestamp, loss, drawdown,
          "paper", "simulated_proxy"};
}

PaperBrokerSnapshot PaperBroker::snapshot() const {
  PaperBrokerSnapshot result;
  result.model = model_;
  result.health = health_;
  result.sequence = sequence_;
  for (const auto& [unused, order] : orders_) {
    (void)unused;
    result.requests.push_back(order.request);
    result.orders.push_back(order.snapshot);
  }
  result.fills = fills_;
  result.positions = query_positions().items;
  for (const auto& [unused, mark] : marks_) {
    (void)unused;
    result.marks.push_back(mark);
  }
  result.cash_paise = cash_paise_;
  result.peak_equity_paise = peak_equity_paise_;
  result.latest_observation_ns = latest_observation_ns_;
  result.pnl_valid = pnl_valid_;
  return result;
}

}  // namespace shaurya::execution
