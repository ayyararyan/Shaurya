#pragma once

#include "shaurya/execution/order_state_machine.hpp"

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace shaurya::execution {

struct IntentBrokerOutcomeReplay {
  std::string event_type;
  std::string update_id;
  std::optional<std::string> broker_order_id;
  std::string source_provenance;
  std::string source_fingerprint;
  std::optional<std::string> error_code;
  std::optional<std::uint64_t> accepted_quantity;
  std::optional<std::uint64_t> accepted_limit_price_paise;
  std::int64_t timestamp_ns{};
};

struct IntentReplayState {
  std::string semantic_fingerprint;
  std::uint64_t first_sequence{};
  std::string disposition{"received"};
  std::optional<std::string> internal_order_id;
  bool ambiguous{};
  std::string strategy_id;
  std::string strategy_run_id;
  std::optional<std::string> risk_decision_json;
  std::optional<IntentBrokerOutcomeReplay> broker_outcome;
};

struct ReconstructedState {
  std::unordered_map<std::string, IntentReplayState> intents;
  std::unordered_map<std::string, OrderAggregate> orders;
  std::unordered_map<std::string, std::string> order_route_tokens;
  std::map<std::string, std::int64_t> positions;
  std::map<std::string, std::int64_t> route_positions;
  std::vector<std::string> incidents;
  std::uint64_t last_broker_update_sequence{};
  std::map<std::string, std::string> broker_update_fingerprints;
  std::vector<std::int64_t> broker_attempt_timestamps_ns;
  bool reconciliation_required{};
  bool global_reconciliation_required{};
  bool safety_stopped{};
  std::string session_state{"unknown"};
};

}  // namespace shaurya::execution
