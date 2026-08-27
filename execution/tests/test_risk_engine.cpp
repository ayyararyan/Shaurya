#include "shaurya/execution/risk.hpp"

#include <algorithm>
#include <iostream>
#include <fstream>
#include <iterator>

using namespace shaurya::execution;

namespace {
RiskConfiguration config() {
  RiskConfiguration value;
  value.configuration_version = "risk-2026-08-27";
  value.trading_date = "2026-08-27";
  value.maximum_observation_age_ns = 100;
  value.maximum_mapping_age_ns = 100;
  value.maximum_greek_age_ns = 100;
  value.maximum_clock_skew_ns = 5;
  value.maximum_order_quantity = 130;
  value.maximum_absolute_instrument_position = 260;
  value.maximum_gross_premium_paise = 1000000000;
  value.maximum_outstanding_orders = 4;
  value.maximum_orders_per_window = 2;
  value.order_rate_window_ns = 1000;
  value.maximum_daily_loss_paise = 100000;
  value.maximum_drawdown_paise = 50000;
  value.configuration_digest = sha256_hex(value.canonical_payload());
  return value;
}
OrderIntent intent(IntentAction action = IntentAction::Place) {
  OrderIntent value;
  value.intent_id = "00000000-0000-4000-8000-000000000001";
  value.strategy_id = "d51";
  value.strategy_run_id = "00000000-0000-4000-8000-000000000002";
  value.execution_session_id = "00000000-0000-4000-8000-000000000003";
  value.created_at_ns = 900; value.expires_at_ns = 2000;
  value.canonical_instrument_id = "NSE:NSE_FNO:NIFTY:future:2026-08-27";
  value.action = action;
  if (action != IntentAction::Cancel) {
    value.side = OrderSide::Buy; value.quantity = 65; value.limit_price_paise = 1000;
    value.product = "NRML"; value.time_in_force = "DAY";
  } else {
    value.target_internal_order_id = "00000000-0000-4000-8000-000000000004";
  }
  return value;
}
RiskSnapshot snapshot() {
  RiskSnapshot value;
  value.now_ns = 1000; value.ready = true;
  value.mapping_state = RiskMappingState::Verified;
  value.route = RoutingRecord{"NSE:NSE_FNO:NIFTY:future:2026-08-27", "58072", "nse_fo",
                              "NIFTY26AUGFUT", 65, 5};
  value.route_trading_date = "2026-08-27";
  value.broker_health = BrokerSessionHealth::Ready;
  value.broker_positions_authoritative = true;
  value.position_marks_authoritative = true;
  value.mapping_age_ns = 50;
  value.maximum_mapping_age_ns = 100;
  value.daily_loss_paise = 0;
  value.drawdown_paise = 0;
  value.pnl_source = "paper";
  value.pnl_provenance = "simulated_proxy";
  value.pnl_timestamp_ns = 950;
  MarketObservation observation;
  observation.canonical_instrument_id = value.route->canonical_instrument_id;
  observation.best_bid_paise = 995; observation.best_ask_paise = 1000;
  observation.cumulative_volume = 100; observation.receive_timestamp_ns = 950;
  observation.source = "dhan"; observation.provenance = "observed";
  value.observation = observation;
  return value;
}
}

int main() {
  int failures = 0;
  const auto expect = [&](bool condition, const char* message) {
    if (!condition) { std::cerr << message << '\n'; ++failures; }
  };
  const RiskEngine engine(config());
  try {
    auto mismatched = config();
    mismatched.configuration_digest = std::string(64U, 'a');
    static_cast<void>(RiskEngine(std::move(mismatched)));
    expect(false, "supplied risk configuration digest was silently rewritten");
  } catch (const std::invalid_argument&) {}
  {
    std::ifstream input(std::string(SHAURYA_EXECUTION_SOURCE_ROOT) +
                        "/tests/fixtures/risk/default_config.json");
    const std::string bytes((std::istreambuf_iterator<char>(input)),
                            std::istreambuf_iterator<char>());
    const auto parsed = RiskConfiguration::parse(bytes);
    expect(parsed.configuration_digest == sha256_hex(parsed.canonical_payload()),
           "strict risk fixture digest");
    try {
      static_cast<void>(RiskConfiguration::parse(bytes.substr(0, bytes.size() - 2) +
          ",\"unknown\":1}"));
      expect(false, "unknown risk field accepted");
    } catch (const std::invalid_argument&) {}
  }
  const auto good = engine.evaluate(intent(), snapshot());
  expect(risk_approved(good), "happy path rejected");
  expect(good.to_json() == engine.evaluate(intent(), snapshot()).to_json(),
         "risk bytes are not deterministic");

  auto killed = snapshot(); killed.kill_switch = true; killed.observation.reset();
  const auto stopped = engine.evaluate(intent(), killed);
  expect(!risk_approved(stopped) && stopped.rejection_code == "kill_switch" &&
             stopped.rules_checked.size() == 1U, "kill precedence");

  auto off_tick = intent(); off_tick.limit_price_paise = 1001;
  const auto tick = engine.evaluate(off_tick, snapshot());
  expect(tick.rejection_code == "invalid_tick_lot_or_size", "off tick accepted");

  auto cancel_state = killed;
  cancel_state.cancel_target_known = true; cancel_state.cancel_target_terminal = false;
  cancel_state.broker_health = BrokerSessionHealth::Unknown;
  const auto cancel = engine.evaluate(intent(IntentAction::Cancel), cancel_state);
  expect(risk_approved(cancel) && cancel.session_state == "reconciliation_required" &&
             RiskDecision::parse(cancel.to_json()) == cancel,
         "risk reducing cancel blocked");

  auto sell = intent(); sell.side = OrderSide::Sell;
  auto no_inventory = snapshot(); no_inventory.exact_token_position = 0;
  expect(engine.evaluate(sell, no_inventory).rejection_code == "token_inventory_unavailable",
         "cross-token sell authorized");
  auto reserved = snapshot();
  reserved.exact_token_position = 65;
  reserved.exact_token_working_sell_quantity = 65;
  expect(engine.evaluate(sell, reserved).rejection_code == "token_inventory_unavailable",
         "working sell inventory not reserved");

  for (const auto state : {RiskMappingState::Missing, RiskMappingState::Stale,
                           RiskMappingState::Partial, RiskMappingState::Ambiguous,
                           RiskMappingState::HashInvalid}) {
    auto invalid_mapping = snapshot(); invalid_mapping.mapping_state = state;
    expect(engine.evaluate(intent(), invalid_mapping).rejection_code == "routing_unverified",
           "invalid mapping state accepted");
  }
  auto stale_mapping = snapshot(); stale_mapping.mapping_age_ns = 101;
  expect(engine.evaluate(intent(), stale_mapping).rejection_code == "routing_stale",
         "mapping age used the wrong freshness maximum");
  auto expired = snapshot(); expired.now_ns = 2000;
  expect(engine.evaluate(intent(), expired).rejection_code == "intent_expired_or_skewed",
         "expiry boundary accepted");
  auto stale = snapshot(); stale.observation->receive_timestamp_ns = 899;
  expect(engine.evaluate(intent(), stale).rejection_code == "observation_unusable",
         "stale observation accepted");
  auto exchange_stale = snapshot(); exchange_stale.observation->exchange_timestamp_ns = 899;
  expect(engine.evaluate(intent(), exchange_stale).rejection_code == "observation_unusable",
         "stale exchange evidence accepted");
  auto unhealthy = snapshot(); unhealthy.broker_health = BrokerSessionHealth::Degraded;
  expect(engine.evaluate(intent(), unhealthy).rejection_code == "broker_unhealthy",
         "degraded broker accepted");
  auto skewed_intent = intent(); skewed_intent.created_at_ns = 1006;
  expect(engine.evaluate(skewed_intent, snapshot()).rejection_code == "intent_expired_or_skewed",
         "future clock skew accepted");
  auto wrong_lot = intent(); wrong_lot.quantity = 64;
  expect(engine.evaluate(wrong_lot, snapshot()).rejection_code == "invalid_tick_lot_or_size",
         "non-lot quantity accepted");
  auto outstanding = snapshot();
  outstanding.working_orders.resize(4, {"working-order", intent().canonical_instrument_id,
                                        "58072", OrderSide::Buy, 1, 1000});
  expect(engine.evaluate(intent(), outstanding).rejection_code == "outstanding_limit",
         "outstanding limit accepted");
  auto rate = snapshot(); rate.recent_order_timestamps_ns = {999, 1000};
  expect(engine.evaluate(intent(), rate).rejection_code == "order_rate_limit",
         "rate limit accepted");
  auto position_limit = snapshot(); position_limit.exact_instrument_position = 260;
  expect(engine.evaluate(intent(), position_limit).rejection_code == "position_limit",
         "position projection limit accepted");
  auto gross_limit = snapshot(); gross_limit.current_gross_premium_paise = 999999999;
  expect(engine.evaluate(intent(), gross_limit).rejection_code == "gross_premium_limit",
         "existing gross premium omitted");
  auto correlation = snapshot(); correlation.expected_execution_session_id =
      "00000000-0000-4000-8000-000000000099";
  expect(engine.evaluate(intent(), correlation).rejection_code == "intent_correlation_mismatch",
         "cross-session intent accepted");

  auto modify = intent(IntentAction::Modify);
  modify.target_internal_order_id = "00000000-0000-4000-8000-000000000004";
  auto modify_snapshot = snapshot();
  modify_snapshot.mutation_target_known = true;
  modify_snapshot.mutation_target = WorkingRiskOrder{*modify.target_internal_order_id,
                                                      modify.canonical_instrument_id, "58072",
                                                      OrderSide::Buy, 65, 1000};
  modify_snapshot.working_orders.push_back(*modify_snapshot.mutation_target);
  expect(risk_approved(engine.evaluate(modify, modify_snapshot)), "valid modify delta rejected");
  auto slot_config = config(); slot_config.maximum_outstanding_orders = 1;
  slot_config.configuration_digest = sha256_hex(slot_config.canonical_payload());
  expect(risk_approved(RiskEngine(slot_config).evaluate(modify, modify_snapshot)),
         "modify did not reuse its exact outstanding-order slot");
  auto exact_identity = modify_snapshot;
  exact_identity.working_orders.push_back(
      {"00000000-0000-4000-8000-000000000099", modify.canonical_instrument_id,
       "58072", OrderSide::Buy, 260, 1000});
  expect(engine.evaluate(modify, exact_identity).rejection_code == "position_limit",
         "modify excluded a different same-instrument working order");

  auto partial_increase = modify_snapshot;
  auto partial_config = config();
  partial_config.maximum_order_quantity = 260;
  partial_config.configuration_digest = sha256_hex(partial_config.canonical_payload());
  RiskEngine partial_engine(partial_config);
  partial_increase.exact_instrument_position = 65;
  partial_increase.current_gross_premium_paise = 65000;
  partial_increase.mutation_target->remaining_quantity = 65;
  partial_increase.mutation_target->cumulative_filled_quantity = 65;
  partial_increase.working_orders = {*partial_increase.mutation_target};
  auto increase = modify;
  increase.quantity = 195;
  const auto increased = partial_engine.evaluate(increase, partial_increase);
  const auto increased_position = std::find_if(
      increased.rules_checked.begin(), increased.rules_checked.end(),
      [](const RuleCheck& rule) { return rule.rule == "position"; });
  const auto increased_gross = std::find_if(
      increased.rules_checked.begin(), increased.rules_checked.end(),
      [](const RuleCheck& rule) { return rule.rule == "gross_premium"; });
  expect(risk_approved(increased) && increased_position != increased.rules_checked.end() &&
             increased_position->projected_value == 195 &&
             increased_gross != increased.rules_checked.end() &&
             increased_gross->projected_value == 195000,
         "partially-filled modify increase double-counted cumulative fills");

  auto partial_decrease = partial_increase;
  partial_decrease.mutation_target->remaining_quantity = 130;
  partial_decrease.working_orders = {*partial_decrease.mutation_target};
  auto decrease = modify;
  decrease.quantity = 130;
  const auto decreased = partial_engine.evaluate(decrease, partial_decrease);
  const auto decreased_position = std::find_if(
      decreased.rules_checked.begin(), decreased.rules_checked.end(),
      [](const RuleCheck& rule) { return rule.rule == "position"; });
  expect(risk_approved(decreased) && decreased_position != decreased.rules_checked.end() &&
             decreased_position->projected_value == 130,
         "partially-filled modify decrease used new total as remaining quantity");

  auto equal_filled = modify;
  equal_filled.quantity = 65;
  expect(partial_engine.evaluate(equal_filled, partial_increase).rejection_code ==
             "modify_target_invalid",
         "modify equal to cumulative fill left a zero-remaining working order");
  auto below_snapshot = partial_increase;
  below_snapshot.mutation_target->cumulative_filled_quantity = 130;
  below_snapshot.working_orders = {*below_snapshot.mutation_target};
  expect(partial_engine.evaluate(equal_filled, below_snapshot).rejection_code ==
             "modify_target_invalid",
         "modify below cumulative fill reached the broker projection");

  auto greek_config = config(); greek_config.greeks.maximum_absolute_delta = 100;
  greek_config.configuration_digest = sha256_hex(greek_config.canonical_payload());
  RiskEngine greek_engine(greek_config);
  auto missing_greek = snapshot();
  expect(greek_engine.evaluate(intent(), missing_greek).rejection_code == "greeks_stale",
         "missing enabled Greek accepted");
  auto excessive_greek = snapshot();
  excessive_greek.greek_snapshot = GreekSnapshot{intent().canonical_instrument_id,
      "risk_provider", "authoritative", true, 1000, 0, 0, 0, 2, 0, 0};
  expect(greek_engine.evaluate(intent(), excessive_greek).rejection_code == "greek_limit",
         "Greek projection limit accepted");
  auto loss = snapshot(); loss.daily_loss_paise = 100001;
  expect(engine.evaluate(intent(), loss).rejection_code == "daily_loss_limit",
         "daily loss above boundary accepted");
  auto drawdown = snapshot(); drawdown.drawdown_paise = 50001;
  expect(engine.evaluate(intent(), drawdown).rejection_code == "drawdown_limit",
         "drawdown above boundary accepted");
  auto unknown_pnl = snapshot(); unknown_pnl.daily_loss_paise.reset();
  expect(engine.evaluate(intent(), unknown_pnl).rejection_code == "pnl_not_authoritative",
         "unknown P&L authority defaulted to zero");
  return failures == 0 ? 0 : 1;
}
