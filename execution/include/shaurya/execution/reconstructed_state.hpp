#pragma once

#include "shaurya/execution/order_state_machine.hpp"

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace shaurya::execution {

struct IntentReplayState {
  std::string semantic_fingerprint;
  std::uint64_t first_sequence{};
  std::string disposition{"received"};
  std::optional<std::string> internal_order_id;
  bool ambiguous{};
};

struct ReconstructedState {
  std::unordered_map<std::string, IntentReplayState> intents;
  std::unordered_map<std::string, OrderAggregate> orders;
  std::unordered_map<std::string, std::string> order_route_tokens;
  std::map<std::string, std::int64_t> positions;
  std::map<std::string, std::int64_t> route_positions;
  std::vector<std::string> incidents;
  bool reconciliation_required{};
  bool global_reconciliation_required{};
  bool safety_stopped{};
  std::string session_state{"unknown"};
};

}  // namespace shaurya::execution
