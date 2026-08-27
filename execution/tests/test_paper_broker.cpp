#include "shaurya/execution/paper_broker.hpp"

#include <iostream>
#include <fstream>
#include <iterator>

using namespace shaurya::execution;

int main() {
  int failures = 0;
  const auto expect = [&](bool condition, const char* message) {
    if (!condition) { std::cerr << message << '\n'; ++failures; }
  };
  PaperBroker broker;
  BrokerOrderRequest request{"00000000-0000-4000-8000-000000000004",
      "00000000-0000-4000-8000-000000000001",
      {"NSE:NSE_FNO:NIFTY:future:2026-08-27", "58072", "nse_fo", "NIFTY26AUGFUT", 65, 5},
      OrderSide::Buy, 65, 1000, 100, 10};
  const auto placed = broker.place(request);
  expect(placed.status == BrokerMutationStatus::Acknowledged &&
             placed.provenance == "simulated_proxy" &&
             placed.broker_correlation_id == "paper-00000001", "paper place");
  MarketObservation before;
  before.canonical_instrument_id = request.route.canonical_instrument_id;
  before.best_bid_paise = 990; before.best_ask_paise = 990;
  before.cumulative_volume = 11; before.receive_timestamp_ns = 100;
  before.source = "dhan"; before.provenance = "observed";
  expect(broker.accept_observation(before).empty(), "placement-time evidence filled");
  before.receive_timestamp_ns = 101;
  const auto fills = broker.accept_observation(before);
  expect(fills.size() == 1U && fills.front().last_fill_quantity == 65U &&
             fills.front().cumulative_filled_quantity == 65U &&
             fills.front().fill_price_paise == 1000U &&
             fills.front().provenance == "simulated_proxy", "proxy full-fill parity");
  before.cumulative_volume = 75; before.receive_timestamp_ns = 102;
  const auto completion = broker.accept_observation(before);
  expect(completion.empty(), "terminal proxy order filled twice");
  expect(broker.query_positions().items.front().quantity == 65, "paper position");
  const auto loss_pnl = broker.query_pnl();
  expect(loss_pnl.status == BrokerQueryStatus::Authoritative &&
             loss_pnl.daily_loss_paise == 650U && loss_pnl.drawdown_paise == 650U &&
             loss_pnl.timestamp_ns == 102,
         "paper fill cashflow/mark loss was not authoritative");
  expect(broker.cancel(request.internal_order_id).status == BrokerMutationStatus::Rejected,
         "filled order cancelled");
  PaperBroker restored(broker.snapshot());
  expect(restored.query_orders().items == broker.query_orders().items &&
             restored.query_trades().items == broker.query_trades().items &&
             restored.query_positions().items == broker.query_positions().items &&
             restored.query_pnl().daily_loss_paise == loss_pnl.daily_loss_paise &&
             restored.query_pnl().drawdown_paise == loss_pnl.drawdown_paise,
         "paper snapshot restart mismatch");
  MarketObservation profitable = before;
  profitable.best_bid_paise = 1010; profitable.best_ask_paise = 1015;
  profitable.cumulative_volume = 76; profitable.receive_timestamp_ns = 103;
  static_cast<void>(restored.accept_observation(profitable));
  expect(restored.query_pnl().daily_loss_paise == 0U &&
             restored.query_pnl().drawdown_paise == 0U,
         "paper peak equity did not advance");
  MarketObservation drawdown = profitable;
  drawdown.best_bid_paise = 995; drawdown.receive_timestamp_ns = 104;
  static_cast<void>(restored.accept_observation(drawdown));
  expect(restored.query_pnl().daily_loss_paise == 325U &&
             restored.query_pnl().drawdown_paise == 975U,
         "paper drawdown was not measured from persisted peak equity");
  PaperBroker drawdown_restored(restored.snapshot());
  expect(drawdown_restored.query_pnl().drawdown_paise == 975U,
         "paper peak/mark evidence was not recovered");
  try {
    auto impossible_snapshot = restored.snapshot();
    impossible_snapshot.peak_equity_paise = -1;
    static_cast<void>(PaperBroker(std::move(impossible_snapshot)));
    expect(false, "negative paper peak equity was accepted");
  } catch (const std::invalid_argument&) {}

  PaperBroker portfolio;
  auto first_leg = request;
  first_leg.internal_order_id = "00000000-0000-4000-8000-000000000071";
  first_leg.side = OrderSide::Buy;
  first_leg.baseline_cumulative_volume = 10;
  auto second_leg = first_leg;
  second_leg.internal_order_id = "00000000-0000-4000-8000-000000000072";
  second_leg.route.canonical_instrument_id =
      "NSE:NSE_FNO:BANKNIFTY:future:2026-08-27";
  second_leg.route.instrument_token = "58073";
  second_leg.route.trading_symbol = "BANKNIFTY26AUGFUT";
  second_leg.limit_price_paise = 2000;
  static_cast<void>(portfolio.place(first_leg));
  static_cast<void>(portfolio.place(second_leg));
  auto first_mark = before;
  first_mark.receive_timestamp_ns = 101; first_mark.cumulative_volume = 11;
  first_mark.best_bid_paise = 990; first_mark.best_ask_paise = 990;
  auto second_mark = first_mark;
  second_mark.canonical_instrument_id = second_leg.route.canonical_instrument_id;
  second_mark.best_bid_paise = 1980; second_mark.best_ask_paise = 1990;
  static_cast<void>(portfolio.accept_observation(first_mark));
  static_cast<void>(portfolio.accept_observation(second_mark));
  const auto portfolio_pnl = portfolio.query_pnl();
  const auto portfolio_snapshot = portfolio.snapshot();
  PaperBroker portfolio_restored(portfolio_snapshot);
  const auto restored_portfolio_snapshot = portfolio_restored.snapshot();
  expect(portfolio.query_positions().items.size() == 2U &&
             portfolio_pnl.status == BrokerQueryStatus::Authoritative &&
             restored_portfolio_snapshot.marks == portfolio_snapshot.marks &&
             restored_portfolio_snapshot.positions == portfolio_snapshot.positions &&
             portfolio_restored.query_pnl().daily_loss_paise ==
                 portfolio_pnl.daily_loss_paise &&
             portfolio_restored.query_pnl().drawdown_paise == portfolio_pnl.drawdown_paise,
         "multi-instrument paper marks/P&L changed across snapshot recovery");

  PaperBroker restart_source;
  auto restart_request = request;
  restart_request.internal_order_id = "00000000-0000-4000-8000-000000000040";
  restart_request.baseline_cumulative_volume = 10;
  expect(restart_source.place(restart_request).status == BrokerMutationStatus::Acknowledged,
         "restart baseline setup failed");
  PaperBroker restarted_working(restart_source.snapshot());
  MarketObservation restart_observation = before;
  restart_observation.receive_timestamp_ns = 101;
  restart_observation.cumulative_volume = 1000;
  expect(restarted_working.accept_observation(restart_observation).empty(),
         "first post-restart observation reused an old volume baseline");
  restart_observation.receive_timestamp_ns = 102;
  restart_observation.cumulative_volume = 1007;
  const auto restart_fill = restarted_working.accept_observation(restart_observation);
  expect(restart_fill.size() == 1U && restart_fill.front().last_fill_quantity == 65U,
         "post-restart volume delta did not produce the deterministic full fill");

  PaperBroker scripted(PaperFillModel::ScriptedV1, true);
  request.internal_order_id = "00000000-0000-4000-8000-000000000005";
  (void)scripted.place(request);
  auto scripted_mark = before;
  scripted_mark.receive_timestamp_ns = 101;
  scripted_mark.cumulative_volume = 12;
  expect(scripted.accept_observation(scripted_mark).empty(),
         "ScriptedV1 unexpectedly generated an automatic crossing fill");
  const std::vector<ScriptedPaperEvent> transcript = {
      {ScriptedPaperEventKind::PartialFill, "u1", request.internal_order_id, 10, 102},
      {ScriptedPaperEventKind::PartialFill, "u1", request.internal_order_id, 10, 102},
      {ScriptedPaperEventKind::Fill, "u2", request.internal_order_id, 65, 103}};
  const auto scripted_fills = scripted.apply_scripted(transcript);
  expect(scripted_fills.size() == 2U && scripted_fills[0].cumulative_filled_quantity == 10U &&
             scripted_fills[1].cumulative_filled_quantity == 65U, "scripted monotonic fills");
  const auto scripted_pnl = scripted.query_pnl();
  PaperBroker restarted_scripted(scripted.snapshot(), true);
  expect(scripted_pnl.status == BrokerQueryStatus::Authoritative &&
             scripted_pnl.daily_loss_paise == 650U &&
             restarted_scripted.query_pnl().daily_loss_paise ==
                 scripted_pnl.daily_loss_paise &&
             restarted_scripted.query_pnl().drawdown_paise == scripted_pnl.drawdown_paise,
         "ScriptedV1 marks/P&L were unavailable or changed across restart");
  {
    std::ifstream fixture(std::string(SHAURYA_EXECUTION_SOURCE_ROOT) +
                          "/tests/fixtures/paper/scripted_partial_fill.json");
    const std::string bytes((std::istreambuf_iterator<char>(fixture)),
                            std::istreambuf_iterator<char>());
    expect(bytes.find("scripted_v1") != std::string::npos &&
               bytes.find("simulated_proxy") != std::string::npos,
           "paper fixture corpus not consumed");
  }
  request.internal_order_id = "00000000-0000-4000-8000-000000000006";
  PaperBroker lost(PaperFillModel::ScriptedV1, true);
  expect(lost.place(request).status == BrokerMutationStatus::Acknowledged, "loss setup place");
  static_cast<void>(lost.apply_scripted({{ScriptedPaperEventKind::SessionLoss, "loss-1", "none", 0, 104}}));
  expect(lost.modify({request.internal_order_id, 65, 1000}).status ==
             BrokerMutationStatus::Ambiguous &&
             lost.cancel(request.internal_order_id).status == BrokerMutationStatus::Ambiguous,
         "paper mutated after session loss");

  request.internal_order_id = "00000000-0000-4000-8000-000000000007";
  PaperBroker invalid_evidence;
  static_cast<void>(invalid_evidence.place(request));
  MarketObservation crossed = before;
  crossed.receive_timestamp_ns = 105;
  crossed.quality_flags = {"crossed_book"};
  expect(invalid_evidence.accept_observation(crossed).empty(), "crossed book filled paper order");
  crossed.quality_flags.clear();
  crossed.exchange_timestamp_ns = request.submitted_at_ns;
  expect(invalid_evidence.accept_observation(crossed).empty(),
         "pre-placement exchange evidence filled paper order");

  PaperBroker mutations;
  request.internal_order_id = "00000000-0000-4000-8000-000000000008";
  expect(mutations.place(request).status == BrokerMutationStatus::Acknowledged &&
             mutations.modify({request.internal_order_id, 65, 1005}).accepted_limit_price_paise ==
                 1005,
         "paper modify acknowledgement terms");
  const auto first_cancel = mutations.cancel(request.internal_order_id);
  const auto second_cancel = mutations.cancel(request.internal_order_id);
  expect(first_cancel.status == BrokerMutationStatus::Acknowledged &&
             first_cancel.terminal_state_confirmed &&
             second_cancel.status == BrokerMutationStatus::Acknowledged &&
             mutations.cancel("00000000-0000-4000-8000-000000000099").status ==
                 BrokerMutationStatus::Rejected,
         "paper cancel idempotency/unknown target");

  PaperBroker sell_broker;
  request.internal_order_id = "00000000-0000-4000-8000-000000000009";
  request.side = OrderSide::Sell;
  request.baseline_cumulative_volume = 20;
  static_cast<void>(sell_broker.place(request));
  MarketObservation unchanged;
  unchanged.canonical_instrument_id = request.route.canonical_instrument_id;
  unchanged.last_trade_paise = 1010; unchanged.cumulative_volume = 20;
  unchanged.receive_timestamp_ns = 101; unchanged.source = "dhan";
  unchanged.provenance = "observed";
  expect(sell_broker.accept_observation(unchanged).empty(),
         "unchanged cumulative volume produced trade fill");
  unchanged.cumulative_volume = 5;
  expect(sell_broker.accept_observation(unchanged).empty(), "volume reset produced fill");
  unchanged.best_bid_paise = 1010; unchanged.cumulative_volume = 6;
  expect(sell_broker.accept_observation(unchanged).size() == 1U,
         "later SELL bid crossing did not fill");
  try { PaperBroker forbidden(PaperFillModel::ScriptedV1); (void)forbidden; expect(false, "script selectable"); }
  catch (const std::invalid_argument&) {}
  return failures == 0 ? 0 : 1;
}
