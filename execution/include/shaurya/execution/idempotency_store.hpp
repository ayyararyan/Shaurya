#pragma once

#include "shaurya/execution/contracts.hpp"
#include "shaurya/execution/execution_ledger.hpp"
#include "shaurya/execution/reconstructed_state.hpp"

#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>

namespace shaurya::execution {
enum class IdempotencyOutcome { NewIntent, Duplicate, Conflict, ReconciliationRequired, SafetyStopped };
struct IdempotencyResult { IdempotencyOutcome outcome{IdempotencyOutcome::Conflict}; std::string disposition; std::optional<std::string> internal_order_id; };
class IdempotencyStore {
 public:
  [[nodiscard]] static IdempotencyStore from_reconstructed(const ReconstructedState& state);
  [[nodiscard]] IdempotencyResult check_or_record(const OrderIntent& intent,
                                                  ExecutionLedger& ledger,
                                                  const ExecutionEvent& intent_received,
                                                  const ExecutionEvent& conflict_incident);
  void update(std::string_view intent_id, std::string disposition,
              std::optional<std::string> internal_order_id = std::nullopt, bool ambiguous = false);
  [[nodiscard]] bool safety_stopped() const noexcept { return safety_stopped_; }
 private:
  std::unordered_map<std::string, IntentReplayState> intents_;
  bool safety_stopped_{};
};
}  // namespace shaurya::execution
