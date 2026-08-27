#pragma once

#include "shaurya/execution/reconciliation.hpp"
#include "shaurya/execution/risk.hpp"
#include "shaurya/execution/instrument_resolver.hpp"
#include "shaurya/execution/execution_ledger.hpp"
#include "shaurya/execution/idempotency_store.hpp"

#include <cstddef>
#include <cstdint>
#include <chrono>
#include <deque>
#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace shaurya::execution {

struct SessionAuditRecord {
  std::string kind;
  std::string correlation_id;
  std::optional<std::string> internal_order_id;
  std::string non_secret_detail;
  ExecutionEvent event;
};

class SessionLedger {
 public:
  virtual ~SessionLedger() = default;
  [[nodiscard]] virtual bool append(const SessionAuditRecord& record) = 0;
  [[nodiscard]] virtual LedgerDurabilityBoundary append_event(const ExecutionEvent& event);
  [[nodiscard]] virtual bool flush() = 0;
  [[nodiscard]] virtual std::optional<ReconstructedState> reconstructed_state() const;
  [[nodiscard]] virtual std::uint64_t last_sequence() const noexcept { return 0U; }
};

class ExecutionLedgerSessionAdapter final : public SessionLedger {
 public:
  [[nodiscard]] static ExecutionLedgerSessionAdapter create_new(const std::filesystem::path& path);
  [[nodiscard]] static ExecutionLedgerSessionAdapter open_existing(const std::filesystem::path& path);
  [[nodiscard]] static ExecutionLedgerSessionAdapter create_new_at(
      int directory_descriptor, std::string basename);
  [[nodiscard]] static ExecutionLedgerSessionAdapter open_existing_at(
      int directory_descriptor, std::string basename);
  [[nodiscard]] bool append(const SessionAuditRecord& record) override;
  [[nodiscard]] LedgerDurabilityBoundary append_event(const ExecutionEvent& event) override;
  [[nodiscard]] bool flush() override { return true; }
  [[nodiscard]] std::optional<ReconstructedState> reconstructed_state() const override;
  [[nodiscard]] std::uint64_t last_sequence() const noexcept override {
    return ledger_.last_sequence();
  }
  [[nodiscard]] ExecutionLedger& ledger() noexcept { return ledger_; }
 private:
  ExecutionLedgerSessionAdapter(ExecutionLedger ledger, ReconstructedState state);
  ExecutionLedger ledger_;
  ReconstructedState state_;
};

class SessionRoutingResolver {
 public:
  virtual ~SessionRoutingResolver() = default;
  [[nodiscard]] virtual ResolutionResult resolve(std::string_view canonical_id) const = 0;
  [[nodiscard]] virtual std::string_view snapshot_digest() const noexcept = 0;
  [[nodiscard]] virtual bool valid_for_trading_date(std::string_view trading_date) const noexcept = 0;
  [[nodiscard]] virtual std::optional<std::int64_t> mapping_timestamp_ns() const noexcept {
    return std::nullopt;
  }
};

class SessionClock {
 public:
  virtual ~SessionClock() = default;
  [[nodiscard]] virtual std::int64_t now_ns() const noexcept = 0;
};

struct SessionIntentResult {
  RiskDecision decision;
  std::optional<BrokerMutationResult> broker_result;
  bool replayed_duplicate{};
  bool safety_stopped{};
};

class ExecutionSession;

// Move-only capability produced by one ExecutionSession. Its private state cannot be
// constructed or rebound by callers, and submit_prepared consumes it exactly once.
class PreparedSessionIntent final {
 public:
  PreparedSessionIntent(PreparedSessionIntent&& other) noexcept;
  PreparedSessionIntent& operator=(PreparedSessionIntent&& other) noexcept;
  PreparedSessionIntent(const PreparedSessionIntent&) = delete;
  PreparedSessionIntent& operator=(const PreparedSessionIntent&) = delete;

  [[nodiscard]] bool requires_broker_submission() const noexcept {
    return !completed_result_.has_value();
  }
  [[nodiscard]] const std::optional<SessionIntentResult>& completed_result() const noexcept {
    return completed_result_;
  }

 private:
  PreparedSessionIntent() = default;
  friend class ExecutionSession;

  ExecutionSession* owner_{};
  bool consumed_{};
  std::optional<SessionIntentResult> completed_result_;
  OrderIntent intent_;
  ResolutionResult resolution_;
  RiskSnapshot snapshot_;
  RiskDecision decision_;
  std::string fingerprint_;
  std::string order_id_;
  std::uint64_t authority_generation_{};
};

struct SessionStopResult {
  std::vector<BrokerMutationResult> cancel_results;
  std::size_t working_orders_seen{};
  std::size_t cancellation_attempts{};
  std::size_t cancellation_refusals{};
  bool cancellation_accounting_complete{};
  bool cancellation_complete{};
  bool reconciliation_exact{};
  bool ledger_flushed{};
  bool stopped_recorded{};
};

struct SessionLaunchEvidence {
  std::string launch_attestation_digest;
  std::string invocation_id;
  std::string execution_session_id;
  std::string operator_id;
  std::string device_id;
  std::string public_key_fingerprint;
  std::string cli_release_digest;
  std::string deployment_manifest_digest;
  std::string executor_build_digest;
  std::string requested_mode;
  std::string confirmation_type;
  std::int64_t launch_timestamp_ns{};

  friend bool operator==(const SessionLaunchEvidence&, const SessionLaunchEvidence&) = default;
};

struct BrokerUpdateEnvelope {
  std::uint64_t sequence{};
  std::string update_id;
  bool session_lost{};
  std::string strategy_id;
  std::string strategy_run_id;
  std::string intent_id;
  std::string internal_order_id;
  OrderEventKind kind{OrderEventKind::BrokerAcknowledged};
  std::optional<std::string> broker_order_id;
  std::optional<std::uint64_t> cumulative_filled_quantity;
  std::optional<std::uint64_t> accepted_quantity;
  std::optional<std::uint64_t> accepted_limit_price_paise;
  std::optional<std::uint64_t> fill_price_paise;
  std::optional<std::string> error_code;
  std::optional<std::string> provenance;
  std::optional<std::int64_t> evidence_timestamp_ns;
};

class SessionStageCoordinator {
 public:
  virtual ~SessionStageCoordinator() = default;
  [[nodiscard]] virtual bool acknowledge_ledger_boundary(std::uint64_t expected_sequence,
                                                          bool broker_attempted) = 0;
  [[nodiscard]] virtual bool reserve_broker_updates(std::size_t maximum_updates) = 0;
  [[nodiscard]] virtual bool dispatch_broker_update(BrokerUpdateEnvelope update) = 0;
  virtual void release_broker_update_reservations() noexcept = 0;
  virtual void before_shutdown_risk_evaluation() {}
};

class ExecutionSession {
 public:
  ExecutionSession(std::string execution_session_id, RiskEngine risk_engine,
                   ReplayedBrokerState replayed_state, SessionLedger& ledger,
                   SessionRoutingResolver& resolver, BrokerAdapter& broker,
                   SessionClock& clock, std::size_t maximum_update_queue = 1024U,
                   std::optional<SessionLaunchEvidence> launch_evidence = std::nullopt);

  [[nodiscard]] bool start();
  [[nodiscard]] bool preflight();
  [[nodiscard]] bool activate();
  void set_stage_coordinator(SessionStageCoordinator* coordinator) noexcept {
    stage_coordinator_ = coordinator;
  }
  [[nodiscard]] bool record_market_observation_accepted(
      std::uint64_t source_sequence, std::string_view source_digest,
      const MarketObservation& observation);
  void accept_observation(MarketObservation observation);
  [[nodiscard]] PreparedSessionIntent prepare_intent(const OrderIntent& intent);
  [[nodiscard]] SessionIntentResult submit_prepared(PreparedSessionIntent prepared);
  [[nodiscard]] SessionIntentResult accept_intent(const OrderIntent& intent);
  [[nodiscard]] bool accept_broker_update(const BrokerUpdateEnvelope& update);
  [[nodiscard]] bool enqueue_broker_update(BrokerUpdateEnvelope update);
  [[nodiscard]] bool drain_broker_updates();
  void activate_kill_switch(std::string reason);
  [[nodiscard]] bool reconcile_after_strategy_reconnect();
  [[nodiscard]] SessionStopResult stop(
      std::optional<std::chrono::steady_clock::time_point> deadline = std::nullopt);

  [[nodiscard]] bool ready() const noexcept { return ready_; }
  [[nodiscard]] bool safety_stopped() const noexcept { return safety_stopped_; }
  [[nodiscard]] bool reconciliation_required() const noexcept { return reconciliation_required_; }

 private:
  [[nodiscard]] LedgerDurabilityBoundary durable_event(const ExecutionEvent& event);
  [[nodiscard]] ExecutionEvent event_for(const OrderIntent* intent, std::string kind,
                                         std::optional<std::string> internal_order_id,
                                         JsonObject payload);
  void force_safety_stop(std::string reason, const OrderIntent* intent = nullptr,
                         std::optional<std::string> internal_order_id = std::nullopt);
  [[nodiscard]] RiskSnapshot capture_risk_snapshot(const OrderIntent& intent,
                                                   const ResolutionResult& resolution) const;
  [[nodiscard]] static std::string internal_order_id(const OrderIntent& intent);

  std::string execution_session_id_;
  RiskEngine risk_engine_;
  ReplayedBrokerState replayed_state_;
  SessionLedger& ledger_;
  SessionRoutingResolver& resolver_;
  BrokerAdapter& broker_;
  SessionClock& clock_;
  Reconciler reconciler_;
  std::size_t maximum_update_queue_{};
  std::deque<BrokerUpdateEnvelope> update_queue_;
  bool started_{};
  bool ready_{};
  bool stopping_{};
  bool kill_switch_{};
  bool safety_stopped_{};
  bool reconciliation_required_{};
  std::optional<MarketObservation> observation_;
  std::map<std::string, MarketObservation> observations_;
  std::vector<std::int64_t> accepted_order_times_ns_;
  std::uint64_t last_update_sequence_{};
  std::uint64_t next_local_update_sequence_{};
  std::map<std::string, std::string> applied_update_fingerprints_;
  std::map<std::string, std::pair<std::string, SessionIntentResult>> outcomes_;
  std::map<std::string, std::string> order_owner_intents_;
  ReconstructedState reconstructed_state_;
  IdempotencyStore idempotency_store_;
  std::optional<std::string> bound_strategy_id_;
  std::optional<std::string> bound_strategy_run_id_;
  bool replay_correlation_conflict_{};
  std::uint64_t event_sequence_{};
  std::optional<SessionLaunchEvidence> launch_evidence_;
  SessionStageCoordinator* stage_coordinator_{};
  std::uint64_t authority_generation_{};
};

}  // namespace shaurya::execution
