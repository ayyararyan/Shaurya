#pragma once

#include "shaurya/execution/broker_adapter.hpp"
#include "shaurya/execution/reconstructed_state.hpp"

#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace shaurya::execution {

struct ReplayedBrokerState {
  std::vector<BrokerOrderSnapshot> orders;
  std::vector<BrokerFillSnapshot> fills;
  std::vector<BrokerPositionSnapshot> positions;
  std::map<std::string, std::int64_t> strategy_desired_positions;
  std::set<std::string> known_instruments;
  std::string broker_source{"paper"};
  std::string position_provenance{"proxy"};
  ReconstructedState reconstructed;
};

struct ReconciliationResult {
  bool exact_agreement{};
  bool safety_stop{};
  std::vector<std::string> incidents;
  ReplayedBrokerState replayed;
  BrokerQueryResult<BrokerOrderSnapshot> broker_orders;
  BrokerQueryResult<BrokerFillSnapshot> broker_fills;
  BrokerQueryResult<BrokerPositionSnapshot> broker_positions;
  PositionSnapshot position_snapshot;
};

class Reconciler {
 public:
  [[nodiscard]] ReconciliationResult compare(
      const ReplayedBrokerState& replayed,
      const BrokerQueryResult<BrokerOrderSnapshot>& broker_orders,
      const BrokerQueryResult<BrokerFillSnapshot>& broker_fills,
      const BrokerQueryResult<BrokerPositionSnapshot>& broker_positions,
      std::string execution_session_id, std::string snapshot_id,
      std::int64_t timestamp_ns) const;
};

}  // namespace shaurya::execution
