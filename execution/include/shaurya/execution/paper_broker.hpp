#pragma once

#include "shaurya/execution/broker_adapter.hpp"

#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace shaurya::execution {

enum class PaperFillModel { D51ProxyV1, ScriptedV1 };
enum class ScriptedPaperEventKind { PartialFill, Fill, Reject, SessionLoss, Ambiguous };

struct ScriptedPaperEvent {
  ScriptedPaperEventKind kind{ScriptedPaperEventKind::Fill};
  std::string update_id;
  std::string internal_order_id;
  std::uint64_t cumulative_filled_quantity{};
  std::int64_t timestamp_ns{};
};

struct PaperMarkSnapshot {
  std::string canonical_instrument_id;
  std::optional<std::uint64_t> best_bid_paise;
  std::optional<std::uint64_t> best_ask_paise;
  std::optional<std::uint64_t> last_trade_paise;
  std::int64_t timestamp_ns{};
  friend bool operator==(const PaperMarkSnapshot&, const PaperMarkSnapshot&) = default;
};

struct PaperBrokerSnapshot {
  PaperFillModel model{PaperFillModel::D51ProxyV1};
  BrokerSessionHealth health{BrokerSessionHealth::Ready};
  std::uint64_t sequence{};
  std::vector<BrokerOrderRequest> requests;
  std::vector<BrokerOrderSnapshot> orders;
  std::vector<BrokerFillSnapshot> fills;
  std::vector<BrokerPositionSnapshot> positions;
  std::vector<PaperMarkSnapshot> marks;
  std::int64_t cash_paise{};
  std::int64_t peak_equity_paise{};
  std::int64_t latest_observation_ns{};
  bool pnl_valid{true};
};

class PaperBroker final : public BrokerAdapter {
 public:
  explicit PaperBroker(PaperFillModel model = PaperFillModel::D51ProxyV1,
                       bool fixture_script_authorized = false);
  explicit PaperBroker(PaperBrokerSnapshot snapshot, bool fixture_script_authorized = false);
  [[nodiscard]] bool shutdown_operations_bounded_nonblocking() const noexcept override {
    return true;
  }

  [[nodiscard]] BrokerMutationResult place(const BrokerOrderRequest& request) override;
  [[nodiscard]] BrokerMutationResult modify(const BrokerModifyRequest& request) override;
  [[nodiscard]] BrokerMutationResult cancel(std::string_view internal_order_id) override;
  [[nodiscard]] BrokerQueryResult<BrokerOrderSnapshot> query_orders() const override;
  [[nodiscard]] BrokerQueryResult<BrokerFillSnapshot> query_trades() const override;
  [[nodiscard]] BrokerQueryResult<BrokerPositionSnapshot> query_positions() const override;
  [[nodiscard]] BrokerSessionHealth session_health() const noexcept override { return health_; }
  [[nodiscard]] BrokerPnlSnapshot query_pnl() const override;

  [[nodiscard]] std::vector<BrokerFillSnapshot> accept_observation(
      const MarketObservation& observation) override;
  [[nodiscard]] std::vector<BrokerFillSnapshot> apply_scripted(
      const std::vector<ScriptedPaperEvent>& events);
  [[nodiscard]] PaperBrokerSnapshot snapshot() const;

 private:
  struct PaperOrder {
    BrokerOrderRequest request;
    BrokerOrderSnapshot snapshot;
    std::uint64_t observed_cumulative_volume{};
    bool volume_reset{};
    bool awaiting_restart_baseline{};
  };

  [[nodiscard]] std::string next_correlation_id();
  [[nodiscard]] BrokerFillSnapshot fill(PaperOrder& order, std::uint64_t cumulative,
                                        std::int64_t timestamp_ns);
  [[nodiscard]] std::optional<std::int64_t> equity_paise() const noexcept;
  void update_peak_equity() noexcept;
  PaperFillModel model_;
  BrokerSessionHealth health_{BrokerSessionHealth::Ready};
  std::uint64_t sequence_{};
  std::map<std::string, PaperOrder> orders_;
  std::vector<BrokerFillSnapshot> fills_;
  std::map<std::string, std::int64_t> positions_;
  std::vector<std::string> applied_script_updates_;
  std::map<std::string, PaperMarkSnapshot> marks_;
  std::int64_t cash_paise_{};
  std::int64_t peak_equity_paise_{};
  std::int64_t latest_observation_ns_{};
  bool pnl_valid_{true};
};

}  // namespace shaurya::execution
