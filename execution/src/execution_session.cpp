#include "shaurya/execution/execution_session.hpp"

#include "shaurya/execution/canonical_json.hpp"
#include "shaurya/execution/ledger_replay.hpp"

#include <algorithm>
#include <limits>
#include <set>
#include <utility>

namespace shaurya::execution {
namespace {

std::string stable_uuid(std::string_view seed) {
  std::string value = sha256_hex(seed);
  value[12] = '4'; value[16] = '8';
  return value.substr(0, 8) + '-' + value.substr(8, 4) + '-' + value.substr(12, 4) + '-' +
         value.substr(16, 4) + '-' + value.substr(20, 12);
}

bool working_state(std::string_view state) {
  return state == "working" || state == "acknowledged" || state == "partially_filled" ||
         state == "ambiguous";
}

bool known_runtime_order_state(std::string_view state) {
  return working_state(state) || state == "filled" || state == "cancelled" ||
         state == "rejected";
}

bool unhealthy_observation(const MarketObservation& observation) {
  static constexpr std::string_view blocked[] = {"stale", "crossed_book", "unusable"};
  const bool invalid_prices =
      (!observation.best_bid_paise && !observation.best_ask_paise &&
       !observation.last_trade_paise) ||
      (observation.best_bid_paise && *observation.best_bid_paise == 0U) ||
      (observation.best_ask_paise && *observation.best_ask_paise == 0U) ||
      (observation.last_trade_paise && *observation.last_trade_paise == 0U) ||
      (observation.best_bid_paise && observation.best_ask_paise &&
       *observation.best_bid_paise > *observation.best_ask_paise);
  const bool invalid_time = observation.receive_timestamp_ns < 0 ||
      (observation.exchange_timestamp_ns &&
       (*observation.exchange_timestamp_ns < 0 ||
        *observation.exchange_timestamp_ns > observation.receive_timestamp_ns));
  return observation.source != "dhan" || observation.provenance != "observed" ||
         invalid_prices || invalid_time ||
         std::any_of(observation.quality_flags.begin(), observation.quality_flags.end(),
                     [](const std::string& flag) {
                       return std::find(std::begin(blocked), std::end(blocked), flag) !=
                              std::end(blocked);
                     });
}

bool valid_runtime_provenance(std::string_view value) {
  return value == "simulated_proxy" || value == "broker_confirmed";
}

bool checked_signed_add(std::int64_t left, std::int64_t right,
                        std::int64_t& result) noexcept {
  if ((right > 0 && left > std::numeric_limits<std::int64_t>::max() - right) ||
      (right < 0 && left < std::numeric_limits<std::int64_t>::min() - right)) return false;
  result = left + right;
  return true;
}

JsonValue text(std::string value) { return JsonValue(std::move(value)); }
JsonValue integer(std::uint64_t value) {
  return JsonValue(JsonInteger{std::to_string(value)});
}

std::string side_name(OrderSide side) { return side == OrderSide::Buy ? "BUY" : "SELL"; }

bool lowercase_digest(std::string_view value) {
  return value.size() == 64U && std::all_of(value.begin(), value.end(), [](char item) {
    return (item >= '0' && item <= '9') || (item >= 'a' && item <= 'f');
  });
}

std::string update_fingerprint(const BrokerUpdateEnvelope& update) {
  return sha256_hex(std::to_string(update.sequence) + "|" + update.strategy_id + "|" +
                    update.strategy_run_id + "|" + update.intent_id + "|" +
                    update.internal_order_id + "|" +
                    std::to_string(static_cast<unsigned>(update.kind)) + "|" +
                    update.broker_order_id.value_or("") + "|" +
                    (update.cumulative_filled_quantity
                         ? std::to_string(*update.cumulative_filled_quantity) : "") + "|" +
                    (update.accepted_quantity ? std::to_string(*update.accepted_quantity) : "") +
                    "|" + (update.accepted_limit_price_paise
                                  ? std::to_string(*update.accepted_limit_price_paise) : "") +
                    "|" + (update.fill_price_paise
                                  ? std::to_string(*update.fill_price_paise) : "") +
                    "|" + update.error_code.value_or("") +
                    "|" + update.provenance.value_or("") + "|" +
                    (update.evidence_timestamp_ns
                         ? std::to_string(*update.evidence_timestamp_ns) : ""));
}

std::string mutation_fingerprint(const BrokerMutationResult& mutation) {
  return sha256_hex(std::to_string(static_cast<unsigned>(mutation.status)) + "|" +
                    mutation.internal_order_id + "|" +
                    mutation.broker_correlation_id.value_or("") + "|" + mutation.provenance +
                    "|" + (mutation.error ? mutation.error->category : "") + "|" +
                    (mutation.accepted_quantity ? std::to_string(*mutation.accepted_quantity) : "") +
                    "|" + (mutation.accepted_limit_price_paise
                                ? std::to_string(*mutation.accepted_limit_price_paise) : "") +
                    "|" + (mutation.terminal_state_confirmed ? "1" : "0"));
}

std::string bounded_broker_error(const std::optional<BrokerError>& error) {
  if (!error) return "broker_rejected";
  static constexpr std::string_view allowed[] = {
      "broker_rejected", "timeout", "broker_exception", "http_failure",
      "malformed_response", "paper_place_rejected", "paper_modify_rejected",
      "paper_unknown_target", "paper_terminal_target", "paper_session_unavailable",
      "broker_outcome_uncertain"};
  return std::find(std::begin(allowed), std::end(allowed), error->category) !=
                 std::end(allowed)
             ? error->category
             : "broker_error_unclassified";
}

bool safe_identifier(std::string_view value, std::size_t maximum = 128U) {
  return !value.empty() && value.size() <= maximum &&
         std::all_of(value.begin(), value.end(), [](char item) {
           return (item >= 'A' && item <= 'Z') || (item >= 'a' && item <= 'z') ||
                  (item >= '0' && item <= '9') || item == '-' || item == '_' || item == '.';
         });
}

bool valid_broker_provenance(std::string_view value) {
  return value == "simulated_proxy" || value == "broker_confirmed" || value == "proxy";
}

bool valid_mutation_result(const BrokerMutationResult& result, std::string_view order_id) {
  if (result.internal_order_id != order_id || !valid_broker_provenance(result.provenance)) return false;
  if (result.broker_correlation_id && !safe_identifier(*result.broker_correlation_id)) return false;
  if (result.error && (!safe_identifier(result.error->category, 64U) ||
                       !safe_identifier(result.error->correlation_id, 128U))) return false;
  return true;
}

}  // namespace

PreparedSessionIntent::PreparedSessionIntent(PreparedSessionIntent&& other) noexcept {
  *this = std::move(other);
}

PreparedSessionIntent& PreparedSessionIntent::operator=(PreparedSessionIntent&& other) noexcept {
  if (this == &other) return *this;
  owner_ = std::exchange(other.owner_, nullptr);
  consumed_ = std::exchange(other.consumed_, true);
  completed_result_ = std::move(other.completed_result_);
  intent_ = std::move(other.intent_);
  resolution_ = std::move(other.resolution_);
  snapshot_ = std::move(other.snapshot_);
  decision_ = std::move(other.decision_);
  fingerprint_ = std::move(other.fingerprint_);
  order_id_ = std::move(other.order_id_);
  authority_generation_ = other.authority_generation_;
  return *this;
}

LedgerDurabilityBoundary SessionLedger::append_event(const ExecutionEvent& event) {
  const auto validated = ExecutionEvent::parse(event.to_json());
  return append({validated.event_type,
                 validated.intent_id.value_or(validated.execution_session_id),
                 validated.internal_order_id, validated.to_json(), validated})
             ? LedgerDurabilityBoundary::Durable
             : LedgerDurabilityBoundary::NotWritten;
}

std::optional<ReconstructedState> SessionLedger::reconstructed_state() const {
  return std::nullopt;
}

ExecutionLedgerSessionAdapter::ExecutionLedgerSessionAdapter(ExecutionLedger ledger,
                                                             ReconstructedState state)
    : ledger_(std::move(ledger)), state_(std::move(state)) {}

ExecutionLedgerSessionAdapter ExecutionLedgerSessionAdapter::create_new(
    const std::filesystem::path& path) {
  return ExecutionLedgerSessionAdapter(ExecutionLedger::create_new(path), ReconstructedState{});
}

ExecutionLedgerSessionAdapter ExecutionLedgerSessionAdapter::open_existing(
    const std::filesystem::path& path) {
  auto state = replay_ledger(path);
  return ExecutionLedgerSessionAdapter(ExecutionLedger::open_existing(path), std::move(state));
}

ExecutionLedgerSessionAdapter ExecutionLedgerSessionAdapter::create_new_at(
    int directory_descriptor, std::string basename) {
  return ExecutionLedgerSessionAdapter(
      ExecutionLedger::create_new_at(directory_descriptor, std::move(basename)),
      ReconstructedState{});
}

ExecutionLedgerSessionAdapter ExecutionLedgerSessionAdapter::open_existing_at(
    int directory_descriptor, std::string basename) {
  auto ledger = ExecutionLedger::open_existing_at(directory_descriptor, std::move(basename));
  auto state = replay_ledger(ledger.verify(LedgerVerificationMode::RetainRecords));
  return ExecutionLedgerSessionAdapter(std::move(ledger), std::move(state));
}

bool ExecutionLedgerSessionAdapter::append(const SessionAuditRecord& record) {
  if (record.event.event_type.empty()) return false;
  return append_event(record.event) == LedgerDurabilityBoundary::Durable;
}

LedgerDurabilityBoundary ExecutionLedgerSessionAdapter::append_event(const ExecutionEvent& event) {
  try {
    static_cast<void>(ledger_.append(ExecutionEvent::parse(event.to_json())));
    return LedgerDurabilityBoundary::Durable;
  } catch (const LedgerError& error) {
    return error.durability_boundary();
  }
}

std::optional<ReconstructedState> ExecutionLedgerSessionAdapter::reconstructed_state() const {
  return state_;
}

ExecutionSession::ExecutionSession(std::string execution_session_id, RiskEngine risk_engine,
                                   ReplayedBrokerState replayed_state, SessionLedger& ledger,
                                   SessionRoutingResolver& resolver, BrokerAdapter& broker,
                                   SessionClock& clock, std::size_t maximum_update_queue,
                                   std::optional<SessionLaunchEvidence> launch_evidence)
    : execution_session_id_(std::move(execution_session_id)),
      risk_engine_(std::move(risk_engine)), replayed_state_(std::move(replayed_state)),
      ledger_(ledger), resolver_(resolver), broker_(broker), clock_(clock),
      maximum_update_queue_(maximum_update_queue),
      reconstructed_state_(ledger.reconstructed_state().value_or(replayed_state_.reconstructed)),
      idempotency_store_(IdempotencyStore::from_reconstructed(reconstructed_state_)),
      launch_evidence_(std::move(launch_evidence)) {
  event_sequence_ = ledger_.last_sequence();
  last_update_sequence_ = reconstructed_state_.last_broker_update_sequence;
  next_local_update_sequence_ = last_update_sequence_;
  applied_update_fingerprints_ = reconstructed_state_.broker_update_fingerprints;
  if (!is_canonical_uuid(execution_session_id_) || maximum_update_queue_ == 0U ||
      (launch_evidence_ &&
       (launch_evidence_->execution_session_id != execution_session_id_ ||
        !is_canonical_uuid(launch_evidence_->invocation_id) ||
        !lowercase_digest(launch_evidence_->launch_attestation_digest) ||
        !lowercase_digest(launch_evidence_->cli_release_digest) ||
        !lowercase_digest(launch_evidence_->deployment_manifest_digest) ||
        !lowercase_digest(launch_evidence_->executor_build_digest) ||
        launch_evidence_->requested_mode != "shadow" ||
        launch_evidence_->confirmation_type != "SHAURYA_SHADOW_LAUNCH" ||
        launch_evidence_->launch_timestamp_ns <= 0)))
    throw std::invalid_argument("invalid_execution_session_configuration");
  for (const auto& [intent_id, replayed_intent] : reconstructed_state_.intents) {
    if (replayed_intent.strategy_id.empty() || replayed_intent.strategy_run_id.empty()) {
      replay_correlation_conflict_ = true;
      continue;
    }
    if (!bound_strategy_id_) {
      bound_strategy_id_ = replayed_intent.strategy_id;
      bound_strategy_run_id_ = replayed_intent.strategy_run_id;
    } else if (*bound_strategy_id_ != replayed_intent.strategy_id ||
               *bound_strategy_run_id_ != replayed_intent.strategy_run_id) {
      replay_correlation_conflict_ = true;
    }
    if (replayed_intent.internal_order_id) {
      const auto owner = order_owner_intents_.find(*replayed_intent.internal_order_id);
      if (owner == order_owner_intents_.end()) {
        order_owner_intents_.emplace(*replayed_intent.internal_order_id, intent_id);
      } else {
        const auto& current = reconstructed_state_.intents.at(owner->second);
        if (replayed_intent.first_sequence < current.first_sequence)
          owner->second = intent_id;
      }
    }
    if (replayed_intent.risk_decision_json) {
      try {
        auto decision = RiskDecision::parse(*replayed_intent.risk_decision_json);
        std::optional<BrokerMutationResult> broker_result;
        if (replayed_intent.broker_outcome) {
          const auto& replay = *replayed_intent.broker_outcome;
          const auto order_id = replayed_intent.internal_order_id.value_or("");
          BrokerMutationStatus status = BrokerMutationStatus::Acknowledged;
          bool terminal = replay.event_type == "cancelled";
          std::optional<BrokerError> error;
          if (replay.event_type == "modify_rejected" || replay.event_type == "cancel_rejected" ||
              replay.event_type == "broker_rejected") {
            status = BrokerMutationStatus::Rejected;
          } else if (replay.event_type == "ambiguous_submission") {
            status = BrokerMutationStatus::Ambiguous;
          } else if (replay.event_type != "broker_acknowledged" &&
                     replay.event_type != "modified" && replay.event_type != "cancelled") {
            throw std::invalid_argument("replay_outcome_type_invalid");
          }
          if (replay.error_code)
            error = BrokerError{*replay.error_code, std::nullopt, replay.update_id};
          broker_result = BrokerMutationResult{
              status, order_id,
              replay.event_type == "broker_acknowledged" ? replay.broker_order_id
                                                          : std::optional<std::string>(replay.update_id),
              replay.source_provenance, std::move(error), terminal,
              replay.accepted_quantity, replay.accepted_limit_price_paise};
          if (mutation_fingerprint(*broker_result) != replay.source_fingerprint)
            throw std::invalid_argument("replay_outcome_fingerprint_mismatch");
        }
        const bool completed_rejection = decision.decision == "rejected" &&
                                         replayed_intent.disposition == "risk_rejected";
        if (broker_result || completed_rejection) {
          outcomes_.emplace(intent_id,
                            std::pair{replayed_intent.semantic_fingerprint,
                                      SessionIntentResult{std::move(decision),
                                                          std::move(broker_result), false,
                                                          replayed_intent.ambiguous}});
        }
      } catch (const std::exception&) {
        replay_correlation_conflict_ = true;
      }
    }
  }
  const auto now = clock_.now_ns();
  const auto window = risk_engine_.configuration().order_rate_window_ns;
  const auto window_start = now < std::numeric_limits<std::int64_t>::min() + window
                                ? std::numeric_limits<std::int64_t>::min()
                                : now - window;
  for (const auto timestamp : reconstructed_state_.broker_attempt_timestamps_ns) {
    if (timestamp > now) replay_correlation_conflict_ = true;
    else if (timestamp > window_start) accepted_order_times_ns_.push_back(timestamp);
  }
}

ExecutionEvent ExecutionSession::event_for(const OrderIntent* intent, std::string kind,
                                           std::optional<std::string> internal_order_id,
                                           JsonObject payload) {
  ExecutionEvent event;
  event.event_id = stable_uuid(execution_session_id_ + ":" + std::to_string(++event_sequence_) +
                               ":" + kind + ":" +
                               (intent ? intent->intent_id : execution_session_id_));
  event.event_type = std::move(kind);
  event.timestamp_ns = clock_.now_ns();
  event.execution_session_id = execution_session_id_;
  if (intent) {
    event.strategy_id = intent->strategy_id;
    event.strategy_run_id = intent->strategy_run_id;
    event.intent_id = intent->intent_id;
    event.internal_order_id = std::move(internal_order_id);
  }
  event.payload = std::move(payload);
  return ExecutionEvent::parse(event.to_json());
}

LedgerDurabilityBoundary ExecutionSession::durable_event(const ExecutionEvent& event) {
  LedgerDurabilityBoundary boundary = LedgerDurabilityBoundary::Uncertain;
  try {
    boundary = ledger_.append_event(ExecutionEvent::parse(event.to_json()));
  } catch (const std::exception&) {
    boundary = LedgerDurabilityBoundary::Uncertain;
  }
  if (boundary != LedgerDurabilityBoundary::Durable) {
    ++authority_generation_;
    ready_ = false;
    safety_stopped_ = true;
    reconciliation_required_ = true;
  }
  return boundary;
}

void ExecutionSession::force_safety_stop(std::string reason, const OrderIntent* intent,
                                         std::optional<std::string> internal_order_id) {
  ++authority_generation_;
  kill_switch_ = true;
  safety_stopped_ = true;
  ready_ = false;
  reconciliation_required_ = true;
  try {
    const auto event = event_for(intent, "safety_stop", std::move(internal_order_id),
                                 {{"reason", text(std::move(reason))}});
    static_cast<void>(ledger_.append_event(event));
  } catch (const std::exception&) {
  }
}

bool ExecutionSession::start() {
  return preflight();
}

bool ExecutionSession::preflight() {
  if (started_) return !safety_stopped_ && !reconciliation_required_;
  started_ = true;
  if (!resolver_.valid_for_trading_date(risk_engine_.configuration().trading_date) ||
      !lowercase_digest(resolver_.snapshot_digest()) || reconstructed_state_.safety_stopped ||
      reconstructed_state_.reconciliation_required ||
      reconstructed_state_.global_reconciliation_required || replay_correlation_conflict_) {
    force_safety_stop("startup_authority_unavailable");
    return false;
  }
  ReconciliationResult result;
  try {
    const auto orders = broker_.query_orders();
    const auto fills = broker_.query_trades();
    const auto positions = broker_.query_positions();
    result = reconciler_.compare(replayed_state_, orders, fills, positions,
        execution_session_id_, stable_uuid(execution_session_id_ + ":startup"), clock_.now_ns());
  } catch (const std::exception&) {
    force_safety_stop("startup_broker_query_exception");
    return false;
  }
  if (!result.exact_agreement || broker_.session_health() != BrokerSessionHealth::Ready) {
    force_safety_stop(result.incidents.empty() ? "broker_not_ready" : result.incidents.front());
    return false;
  }
  return durable_event(event_for(nullptr, "reconciliation_completed", std::nullopt,
                                 {{"reason", text("startup_exact")}})) ==
         LedgerDurabilityBoundary::Durable;
}

bool ExecutionSession::activate() {
  if (ready_) return true;
  if (!started_ || stopping_ || safety_stopped_ || reconciliation_required_ || !observation_)
    return false;
  JsonObject session_payload{{"mode", text("shadow")},
                             {"routing_snapshot_digest",
                              text(std::string(resolver_.snapshot_digest()))}};
  if (launch_evidence_) {
    session_payload.emplace("launch_attestation_digest",
                            text(launch_evidence_->launch_attestation_digest));
    session_payload.emplace("invocation_id", text(launch_evidence_->invocation_id));
    session_payload.emplace("operator_id", text(launch_evidence_->operator_id));
    session_payload.emplace("device_id", text(launch_evidence_->device_id));
    session_payload.emplace("public_key_fingerprint",
                            text(launch_evidence_->public_key_fingerprint));
    session_payload.emplace("cli_release_digest", text(launch_evidence_->cli_release_digest));
    session_payload.emplace("deployment_manifest_digest",
                            text(launch_evidence_->deployment_manifest_digest));
    session_payload.emplace("executor_build_digest",
                            text(launch_evidence_->executor_build_digest));
    session_payload.emplace("requested_mode", text(launch_evidence_->requested_mode));
    session_payload.emplace("confirmation_type", text(launch_evidence_->confirmation_type));
    session_payload.emplace("launch_timestamp_ns",
                            JsonValue(JsonInteger{
                                std::to_string(launch_evidence_->launch_timestamp_ns)}));
  }
  const bool activated = durable_event(event_for(nullptr, "session_started", std::nullopt,
                                                 std::move(session_payload))) ==
                         LedgerDurabilityBoundary::Durable;
  if (activated != ready_) ++authority_generation_;
  ready_ = activated;
  return ready_;
}

bool ExecutionSession::record_market_observation_accepted(
    std::uint64_t source_sequence, std::string_view source_digest,
    const MarketObservation& observation) {
  if (!started_ || stopping_ || source_sequence == 0U || !lowercase_digest(source_digest) ||
      unhealthy_observation(observation)) return false;
  JsonObject payload{
      {"best_ask_paise", observation.best_ask_paise
                               ? integer(*observation.best_ask_paise) : JsonValue()},
      {"best_bid_paise", observation.best_bid_paise
                               ? integer(*observation.best_bid_paise) : JsonValue()},
      {"canonical_instrument_id", text(observation.canonical_instrument_id)},
      {"cumulative_volume", integer(observation.cumulative_volume)},
      {"last_trade_paise", observation.last_trade_paise
                                 ? integer(*observation.last_trade_paise) : JsonValue()},
      {"provenance", text(observation.provenance)},
      {"receive_timestamp_ns", JsonValue(JsonInteger{
                                   std::to_string(observation.receive_timestamp_ns)})},
      {"source", text(observation.source)},
      {"source_digest", text(std::string(source_digest))},
      {"source_sequence", integer(source_sequence)}};
  return durable_event(event_for(
      nullptr, "market_observation_accepted", std::nullopt,
      std::move(payload))) == LedgerDurabilityBoundary::Durable;
}

void ExecutionSession::accept_observation(MarketObservation observation) {
  if (!started_ || stopping_) return;
  if (unhealthy_observation(observation)) {
    activate_kill_switch("market_observation_unusable");
    return;
  }
  observation_ = std::move(observation);
  observations_.insert_or_assign(observation_->canonical_instrument_id, *observation_);
  const auto possible_updates = static_cast<std::size_t>(std::count_if(
      reconstructed_state_.orders.begin(), reconstructed_state_.orders.end(),
      [&](const auto& item) {
        return item.second.canonical_instrument_id == observation_->canonical_instrument_id &&
               (item.second.state == OrderState::Acknowledged ||
                item.second.state == OrderState::PartiallyFilled);
      }));
  if (stage_coordinator_ && !stage_coordinator_->reserve_broker_updates(possible_updates)) {
    force_safety_stop("broker_update_capacity_unavailable");
    return;
  }
  struct ReservationGuard {
    SessionStageCoordinator* coordinator;
    ~ReservationGuard() {
      if (coordinator) coordinator->release_broker_update_reservations();
    }
  } reservation_guard{stage_coordinator_};
  std::vector<BrokerFillSnapshot> fills;
  try {
    fills = broker_.accept_observation(*observation_);
  } catch (const std::exception&) {
    force_safety_stop("paper_observation_exception");
    return;
  }
  for (const auto& fill : fills) {
    const auto order = reconstructed_state_.orders.find(fill.internal_order_id);
    const auto owner = order_owner_intents_.find(fill.internal_order_id);
    const auto intent = owner == order_owner_intents_.end()
        ? reconstructed_state_.intents.end()
        : reconstructed_state_.intents.find(owner->second);
    if (order == reconstructed_state_.orders.end() || owner == order_owner_intents_.end() ||
        intent == reconstructed_state_.intents.end()) {
      force_safety_stop("paper_fill_unknown_correlation");
      return;
    }
    BrokerUpdateEnvelope update;
    if (next_local_update_sequence_ == std::numeric_limits<std::uint64_t>::max()) {
      force_safety_stop("paper_update_sequence_overflow");
      return;
    }
    update.sequence = ++next_local_update_sequence_;
    update.update_id = fill.fill_id;
    update.strategy_id = intent->second.strategy_id;
    update.strategy_run_id = intent->second.strategy_run_id;
    update.intent_id = intent->first;
    update.internal_order_id = fill.internal_order_id;
    update.kind = OrderEventKind::FillUpdate;
    update.cumulative_filled_quantity = fill.cumulative_filled_quantity;
    update.fill_price_paise = fill.fill_price_paise;
    update.provenance = fill.provenance;
    update.evidence_timestamp_ns = fill.evidence_timestamp_ns;
    if (stage_coordinator_) {
      if (!stage_coordinator_->dispatch_broker_update(std::move(update))) return;
    } else if (!accept_broker_update(update)) {
      return;
    }
  }
  if (!ready_) (void)activate();
}

RiskSnapshot ExecutionSession::capture_risk_snapshot(
    const OrderIntent& intent, const ResolutionResult& resolution) const {
  RiskSnapshot snapshot;
  snapshot.now_ns = clock_.now_ns();
  snapshot.kill_switch = kill_switch_ || stopping_ || safety_stopped_;
  snapshot.ready = ready_;
  snapshot.reconciliation_required = reconciliation_required_;
  snapshot.mapping_state = resolution.record ? RiskMappingState::Verified : RiskMappingState::Missing;
  snapshot.route = resolution.record;
  snapshot.route_trading_date = risk_engine_.configuration().trading_date;
  snapshot.maximum_mapping_age_ns = risk_engine_.configuration().maximum_mapping_age_ns;
  if (const auto timestamp = resolver_.mapping_timestamp_ns(); timestamp && *timestamp >= 0 &&
      snapshot.now_ns >= *timestamp) {
    snapshot.mapping_age_ns = snapshot.now_ns - *timestamp;
  } else {
    snapshot.mapping_state = resolution.record ? RiskMappingState::Ambiguous : RiskMappingState::Missing;
    snapshot.mapping_age_ns = std::numeric_limits<std::int64_t>::max();
  }
  snapshot.expected_execution_session_id = execution_session_id_;
  snapshot.expected_strategy_id = bound_strategy_id_.value_or(intent.strategy_id);
  snapshot.expected_strategy_run_id = bound_strategy_run_id_.value_or(intent.strategy_run_id);
  snapshot.broker_health = broker_.session_health();
  if (const auto observed = observations_.find(intent.canonical_instrument_id);
      observed != observations_.end()) snapshot.observation = observed->second;
  snapshot.recent_order_timestamps_ns = accepted_order_times_ns_;
  const auto positions = broker_.query_positions();
  snapshot.broker_positions_authoritative = positions.authoritative();
  snapshot.position_marks_authoritative = positions.authoritative();
  std::set<std::string> position_instruments;
  std::set<std::string> position_tokens;
  if (positions.authoritative() && valid_runtime_provenance(positions.provenance)) {
    for (const auto& position : positions.items) {
      const auto runtime_route = resolver_.resolve(position.canonical_instrument_id);
      if (!is_canonical_instrument_id(position.canonical_instrument_id) ||
          position.instrument_token.empty() || position.quantity == 0 ||
          !valid_runtime_provenance(position.provenance) || !runtime_route.record ||
          runtime_route.record->canonical_instrument_id != position.canonical_instrument_id ||
          runtime_route.record->instrument_token != position.instrument_token ||
          !position_instruments.insert(position.canonical_instrument_id).second ||
          !position_tokens.insert(position.instrument_token).second) {
        snapshot.reconciliation_required = true;
        snapshot.broker_positions_authoritative = false;
        snapshot.position_marks_authoritative = false;
        continue;
      }
      if (position.canonical_instrument_id == intent.canonical_instrument_id) {
        std::int64_t updated{};
        if (!checked_signed_add(snapshot.exact_instrument_position, position.quantity, updated)) {
          snapshot.reconciliation_required = true;
          snapshot.broker_positions_authoritative = false;
        } else {
          snapshot.exact_instrument_position = updated;
        }
      }
      if (snapshot.route && position.instrument_token == snapshot.route->instrument_token) {
        std::int64_t updated{};
        if (!checked_signed_add(snapshot.exact_token_position, position.quantity, updated)) {
          snapshot.reconciliation_required = true;
          snapshot.broker_positions_authoritative = false;
        } else {
          snapshot.exact_token_position = updated;
        }
      }
      std::uint64_t absolute_quantity = position.quantity == std::numeric_limits<std::int64_t>::min()
                                            ? static_cast<std::uint64_t>(
                                                  std::numeric_limits<std::int64_t>::max()) + 1U
                                            : static_cast<std::uint64_t>(
                                                  position.quantity < 0 ? -position.quantity
                                                                        : position.quantity);
      std::uint64_t mark = 0U;
      const auto marked = observations_.find(position.canonical_instrument_id);
      if (marked != observations_.end() && !unhealthy_observation(marked->second) &&
          marked->second.receive_timestamp_ns >= 0 &&
          snapshot.now_ns >= marked->second.receive_timestamp_ns &&
          snapshot.now_ns - marked->second.receive_timestamp_ns <=
              risk_engine_.configuration().maximum_observation_age_ns) {
        mark = std::max({marked->second.best_bid_paise.value_or(0U),
                         marked->second.best_ask_paise.value_or(0U),
                         marked->second.last_trade_paise.value_or(0U)});
      }
      if (position.quantity != 0 && mark == 0U) snapshot.position_marks_authoritative = false;
      if (mark != 0U && absolute_quantity <=
                             std::numeric_limits<std::uint64_t>::max() / mark &&
          snapshot.current_gross_premium_paise <=
              std::numeric_limits<std::uint64_t>::max() - absolute_quantity * mark) {
        snapshot.current_gross_premium_paise += absolute_quantity * mark;
      } else if (absolute_quantity != 0U) {
        snapshot.current_gross_premium_paise = std::numeric_limits<std::uint64_t>::max();
      }
    }
  } else {
    snapshot.reconciliation_required = true;
  }
  const auto orders = broker_.query_orders();
  std::set<std::string> order_ids;
  if (orders.authoritative() && valid_runtime_provenance(orders.provenance)) {
    for (const auto& order : orders.items) {
      const auto runtime_route = resolver_.resolve(order.canonical_instrument_id);
      if (!order_ids.insert(order.internal_order_id).second ||
          !is_canonical_uuid(order.internal_order_id) ||
          !is_canonical_instrument_id(order.canonical_instrument_id) ||
          order.instrument_token.empty() || order.quantity == 0U ||
          order.limit_price_paise == 0U || !known_runtime_order_state(order.state) ||
          !valid_runtime_provenance(order.provenance) || !runtime_route.record ||
          runtime_route.record->canonical_instrument_id != order.canonical_instrument_id ||
          runtime_route.record->instrument_token != order.instrument_token ||
          order.cumulative_filled_quantity > order.quantity) {
        snapshot.reconciliation_required = true;
        continue;
      }
      if (working_state(order.state)) {
        snapshot.working_orders.push_back(
            {order.internal_order_id, order.canonical_instrument_id, order.instrument_token, order.side,
             order.quantity - order.cumulative_filled_quantity, order.limit_price_paise});
        if (snapshot.route && order.instrument_token == snapshot.route->instrument_token &&
            order.side == OrderSide::Sell) {
          const auto remaining = order.quantity - order.cumulative_filled_quantity;
          if (snapshot.exact_token_working_sell_quantity >
              std::numeric_limits<std::uint64_t>::max() - remaining) {
            snapshot.reconciliation_required = true;
          } else {
            snapshot.exact_token_working_sell_quantity += remaining;
          }
        }
      }
      if (intent.target_internal_order_id &&
          order.internal_order_id == *intent.target_internal_order_id) {
        snapshot.mutation_target_known = true;
        snapshot.mutation_target_terminal = !working_state(order.state);
        snapshot.mutation_target = WorkingRiskOrder{
            order.internal_order_id, order.canonical_instrument_id, order.instrument_token, order.side,
            order.quantity - order.cumulative_filled_quantity, order.limit_price_paise,
            order.cumulative_filled_quantity};
        snapshot.cancel_target_known = true;
        snapshot.cancel_target_terminal = !working_state(order.state);
        snapshot.cancel_target_filled_quantity = order.cumulative_filled_quantity;
      }
    }
  } else {
    snapshot.reconciliation_required = true;
  }
  const auto pnl = broker_.query_pnl();
  if (pnl.status == BrokerQueryStatus::Authoritative && pnl.timestamp_ns > 0 &&
      pnl.source == "paper" && pnl.provenance == "simulated_proxy") {
    snapshot.daily_loss_paise = pnl.daily_loss_paise;
    snapshot.drawdown_paise = pnl.drawdown_paise;
    snapshot.pnl_source = pnl.source;
    snapshot.pnl_provenance = pnl.provenance;
    snapshot.pnl_timestamp_ns = pnl.timestamp_ns;
  }
  if (risk_engine_.configuration().greeks.maximum_absolute_delta ||
      risk_engine_.configuration().greeks.maximum_absolute_gamma ||
      risk_engine_.configuration().greeks.maximum_absolute_vega) {
    const auto greek = broker_.query_greeks(intent.canonical_instrument_id);
    if (greek.status == BrokerQueryStatus::Authoritative) {
      snapshot.greek_snapshot = GreekSnapshot{
          greek.canonical_instrument_id, greek.source, greek.provenance, true,
          greek.timestamp_ns, greek.current_delta, greek.current_gamma, greek.current_vega,
          greek.delta_per_unit, greek.gamma_per_unit, greek.vega_per_unit};
    }
  }
  return snapshot;
}

std::string ExecutionSession::internal_order_id(const OrderIntent& intent) {
  return stable_uuid(intent.intent_id + ":internal-order");
}

PreparedSessionIntent ExecutionSession::prepare_intent(const OrderIntent& intent) {
  PreparedSessionIntent prepared;
  prepared.owner_ = this;
  prepared.authority_generation_ = authority_generation_;
  const auto complete = [&](SessionIntentResult result) {
    prepared.completed_result_ = std::move(result);
    return std::move(prepared);
  };
  try {
    static_cast<void>(OrderIntent::parse(intent.to_json()));
  } catch (const JsonError&) {
    throw std::invalid_argument("invalid_parsed_order_intent");
  }
  const std::string fingerprint = intent.semantic_fingerprint();
  const auto idempotency = idempotency_store_.check(intent);
  if (idempotency.outcome == IdempotencyOutcome::Duplicate ||
      idempotency.outcome == IdempotencyOutcome::ReconciliationRequired) {
    if (const auto existing = outcomes_.find(intent.intent_id); existing != outcomes_.end()) {
      auto replay = existing->second.second;
      replay.replayed_duplicate = true;
      return complete(std::move(replay));
    }
    force_safety_stop("duplicate_outcome_unavailable", &intent, idempotency.internal_order_id);
    RiskSnapshot stopped;
    stopped.now_ns = clock_.now_ns();
    stopped.kill_switch = true;
    stopped.idempotency = RiskIdempotencyState::ReconciliationRequired;
    auto decision = risk_engine_.evaluate(intent, stopped);
    return complete({std::move(decision), std::nullopt, true, true});
  }
  if (idempotency.outcome == IdempotencyOutcome::Conflict) {
    RiskSnapshot conflict;
    conflict.now_ns = clock_.now_ns();
    conflict.ready = ready_;
    conflict.idempotency = RiskIdempotencyState::Conflict;
    conflict.expected_execution_session_id = execution_session_id_;
    auto decision = risk_engine_.evaluate(intent, conflict);
    force_safety_stop("intent_payload_conflict", &intent, idempotency.internal_order_id);
    idempotency_store_.record_conflict_durable();
    static_cast<void>(durable_event(event_for(
        &intent, "risk_rejected", std::nullopt,
        {{"broker_call_count", integer(0U)},
         {"configuration_digest", text(decision.configuration_digest)},
         {"decision_id", text(decision.decision_id)},
         {"risk_decision", parse_json(decision.to_json())},
         {"rejection_code", text(decision.rejection_code.value_or("intent_payload_conflict"))}})));
    return complete({std::move(decision), std::nullopt, false, true});
  }
  if (idempotency.outcome == IdempotencyOutcome::SafetyStopped &&
      intent.action != IntentAction::Cancel) {
    RiskSnapshot stopped;
    stopped.now_ns = clock_.now_ns(); stopped.kill_switch = true;
    auto stopped_decision = risk_engine_.evaluate(intent, stopped);
    return complete({std::move(stopped_decision), std::nullopt, false, true});
  }

  const auto received = event_for(
      &intent, "intent_received", std::nullopt,
      {{"canonical_instrument_id", text(intent.canonical_instrument_id)},
       {"semantic_fingerprint", text(fingerprint)}});
  if (durable_event(received) != LedgerDurabilityBoundary::Durable) {
    RiskSnapshot stopped; stopped.now_ns = clock_.now_ns(); stopped.kill_switch = true;
    auto stopped_decision = risk_engine_.evaluate(intent, stopped);
    return complete({std::move(stopped_decision), std::nullopt, false, true});
  }
  idempotency_store_.record_durable(intent, event_sequence_);
  reconstructed_state_.intents.emplace(
      intent.intent_id,
      IntentReplayState{fingerprint, event_sequence_, "received", std::nullopt, false,
                        intent.strategy_id, intent.strategy_run_id,
                        std::nullopt, std::nullopt});

  const std::string order_id = intent.target_internal_order_id.value_or(internal_order_id(intent));
  const auto resolution = resolver_.resolve(intent.canonical_instrument_id);
  JsonObject mapping_payload;
  if (resolution.record) {
    mapping_payload = {{"canonical_instrument_id", text(resolution.record->canonical_instrument_id)},
                       {"exchange_segment", text(resolution.record->exchange_segment)},
                       {"instrument_token", text(resolution.record->instrument_token)},
                       {"lot_size", integer(resolution.record->lot_size)},
                       {"routing_snapshot_digest", text(std::string(resolver_.snapshot_digest()))},
                       {"tick_size_paise", integer(resolution.record->tick_size_paise)},
                       {"trading_symbol", text(resolution.record->trading_symbol)}};
  } else {
    mapping_payload = {{"error_code", text("mapping_not_found")},
                       {"routing_snapshot_digest",
                        text(std::string(resolver_.snapshot_digest()))}};
  }
  if (durable_event(event_for(&intent, resolution.record ? "mapping_validated" : "mapping_refused",
                              resolution.record ? std::optional<std::string>(order_id) : std::nullopt,
                              std::move(mapping_payload))) != LedgerDurabilityBoundary::Durable) {
    RiskSnapshot stopped; stopped.now_ns = clock_.now_ns(); stopped.kill_switch = true;
    auto decision = risk_engine_.evaluate(intent, stopped);
    return complete({std::move(decision), std::nullopt, false, true});
  }
  RiskSnapshot snapshot;
  try {
    snapshot = capture_risk_snapshot(intent, resolution);
  } catch (const std::exception&) {
    force_safety_stop("risk_snapshot_query_exception", &intent, order_id);
    RiskSnapshot stopped; stopped.now_ns = clock_.now_ns(); stopped.kill_switch = true;
    auto decision = risk_engine_.evaluate(intent, stopped);
    return complete({std::move(decision), std::nullopt, false, true});
  }
  auto decision = risk_engine_.evaluate(intent, snapshot);
  static_cast<void>(RiskDecision::parse(decision.to_json()));
  const auto decision_event = risk_approved(decision)
      ? event_for(&intent, "risk_approved", order_id,
                  {{"broker_call_count", integer(0U)},
                   {"configuration_digest", text(decision.configuration_digest)},
                   {"decision_id", text(decision.decision_id)},
                   {"risk_decision", parse_json(decision.to_json())}})
      : event_for(&intent, "risk_rejected", std::nullopt,
                  {{"broker_call_count", integer(0U)},
                   {"configuration_digest", text(decision.configuration_digest)},
                   {"decision_id", text(decision.decision_id)},
                   {"risk_decision", parse_json(decision.to_json())},
                   {"rejection_code", text(decision.rejection_code.value_or("risk_rejected"))}});
  if (durable_event(decision_event) != LedgerDurabilityBoundary::Durable) {
    return complete({std::move(decision), std::nullopt, false, true});
  }
  if (!risk_approved(decision)) {
    SessionIntentResult result{decision, std::nullopt, false, safety_stopped_};
    outcomes_.emplace(intent.intent_id, std::pair{fingerprint, result});
    idempotency_store_.update(intent.intent_id, "risk_rejected");
    reconstructed_state_.intents.at(intent.intent_id).disposition = "risk_rejected";
    return complete(std::move(result));
  }
  if (!bound_strategy_id_) {
    bound_strategy_id_ = intent.strategy_id;
    bound_strategy_run_id_ = intent.strategy_run_id;
  }

  ExecutionEvent attempt;
  if (intent.action == IntentAction::Place) {
    attempt = event_for(&intent, "submission_started", order_id,
                        {{"baseline_cumulative_volume",
                          integer(snapshot.observation ? snapshot.observation->cumulative_volume : 0U)},
                         {"canonical_instrument_id", text(intent.canonical_instrument_id)},
                         {"limit_price_paise", integer(*intent.limit_price_paise)},
                         {"quantity", integer(*intent.quantity)},
                         {"route_digest", text(std::string(resolver_.snapshot_digest()))},
                         {"side", text(side_name(*intent.side))}});
  } else if (intent.action == IntentAction::Modify) {
    attempt = event_for(&intent, "modify_requested", order_id,
                        {{"limit_price_paise", integer(*intent.limit_price_paise)},
                         {"quantity", integer(*intent.quantity)},
                         {"update_id", text(stable_uuid(intent.intent_id + ":modify-request"))}});
  } else {
    attempt = event_for(&intent, "cancel_requested", order_id,
                        {{"update_id", text(stable_uuid(intent.intent_id + ":cancel-request"))}});
  }
  TransitionResult attempt_transition;
  if (intent.action == IntentAction::Place) {
    OrderAggregate aggregate;
    aggregate.internal_order_id = order_id;
    aggregate.canonical_instrument_id = intent.canonical_instrument_id;
    aggregate.route_digest = std::string(resolver_.snapshot_digest());
    aggregate.side = *intent.side;
    aggregate.original_quantity = *intent.quantity;
    aggregate.effective_quantity = *intent.quantity;
    aggregate.limit_price_paise = *intent.limit_price_paise;
    attempt_transition = apply_order_update(
        aggregate, {OrderEventKind::SubmissionStarted, attempt.event_id, std::nullopt,
                    std::nullopt, std::nullopt, std::nullopt});
  } else {
    const auto existing_order = reconstructed_state_.orders.find(order_id);
    if (existing_order == reconstructed_state_.orders.end()) {
      force_safety_stop("mutation_target_missing_from_replay", &intent, order_id);
      return complete({std::move(decision), std::nullopt, false, true});
    }
    attempt_transition = apply_order_update(
        existing_order->second,
        {intent.action == IntentAction::Modify ? OrderEventKind::ModifyRequested
                                               : OrderEventKind::CancelRequested,
         attempt.event_id, std::nullopt, std::nullopt,
         intent.action == IntentAction::Modify ? intent.quantity : std::nullopt,
         intent.action == IntentAction::Modify ? intent.limit_price_paise : std::nullopt});
  }
  if (attempt_transition.error_code) {
    force_safety_stop(*attempt_transition.error_code, &intent, order_id);
    return complete({std::move(decision), std::nullopt, false, true});
  }
  if (durable_event(attempt) != LedgerDurabilityBoundary::Durable) {
    return complete({std::move(decision), std::nullopt, false, true});
  }
  if (intent.action != IntentAction::Cancel) {
    accepted_order_times_ns_.push_back(attempt.timestamp_ns);
    reconstructed_state_.broker_attempt_timestamps_ns.push_back(attempt.timestamp_ns);
    const auto window = risk_engine_.configuration().order_rate_window_ns;
    const auto window_start = attempt.timestamp_ns <
                                      std::numeric_limits<std::int64_t>::min() + window
                                  ? std::numeric_limits<std::int64_t>::min()
                                  : attempt.timestamp_ns - window;
    std::erase_if(accepted_order_times_ns_, [&](const std::int64_t timestamp) {
      return timestamp <= window_start;
    });
  }
  reconstructed_state_.orders.insert_or_assign(order_id, attempt_transition.aggregate);
  auto& replayed_intent = reconstructed_state_.intents.at(intent.intent_id);
  replayed_intent.internal_order_id = order_id;
  if (intent.action == IntentAction::Place) {
    const auto [owner, owner_inserted] = order_owner_intents_.emplace(order_id, intent.intent_id);
    if (!owner_inserted && owner->second != intent.intent_id) {
      force_safety_stop("internal_order_owner_conflict", &intent, order_id);
      return complete({std::move(decision), std::nullopt, false, true});
    }
  } else if (!order_owner_intents_.contains(order_id)) {
    force_safety_stop("internal_order_owner_missing", &intent, order_id);
    return complete({std::move(decision), std::nullopt, false, true});
  }
  replayed_intent.disposition = intent.action == IntentAction::Place
                                    ? "submission_started"
                                    : intent.action == IntentAction::Modify
                                          ? "modify_requested" : "cancel_requested";
  if (resolution.record)
    reconstructed_state_.order_route_tokens.insert_or_assign(order_id,
                                                              resolution.record->instrument_token);
  prepared.intent_ = intent;
  prepared.resolution_ = resolution;
  prepared.snapshot_ = snapshot;
  prepared.decision_ = decision;
  prepared.fingerprint_ = fingerprint;
  prepared.order_id_ = order_id;
  return prepared;
}

SessionIntentResult ExecutionSession::submit_prepared(PreparedSessionIntent prepared) {
  if (prepared.owner_ != this || prepared.consumed_)
    throw std::invalid_argument("prepared_intent_session_mismatch");
  prepared.owner_ = nullptr;
  prepared.consumed_ = true;
  if (prepared.completed_result_) return std::move(*prepared.completed_result_);
  const auto& intent = prepared.intent_;
  const auto& resolution = prepared.resolution_;
  const auto& snapshot = prepared.snapshot_;
  auto decision = std::move(prepared.decision_);
  const auto& fingerprint = prepared.fingerprint_;
  const auto& order_id = prepared.order_id_;
  if (prepared.authority_generation_ != authority_generation_ || stopping_ ||
      (!ready_ && intent.action != IntentAction::Cancel)) {
    reconciliation_required_ = true;
    safety_stopped_ = true;
    static_cast<void>(durable_event(event_for(
        &intent, "reconciliation_required", order_id,
        {{"reason", text("prepared_authority_revoked_before_broker")}})));
    return {std::move(decision), std::nullopt, false, true};
  }
  auto& replayed_intent = reconstructed_state_.intents.at(intent.intent_id);
  BrokerMutationResult mutation;
  if (stage_coordinator_ &&
      !stage_coordinator_->acknowledge_ledger_boundary(ledger_.last_sequence(), false)) {
    force_safety_stop("ledger_command_not_acknowledged", &intent, order_id);
    RiskSnapshot stopped; stopped.now_ns = clock_.now_ns(); stopped.kill_switch = true;
    auto stopped_decision = risk_engine_.evaluate(intent, stopped);
    return {std::move(stopped_decision), std::nullopt, false, true};
  }
  try {
    if (intent.action == IntentAction::Place) {
      mutation = broker_.place({order_id, intent.intent_id, *resolution.record, *intent.side,
                                *intent.quantity, *intent.limit_price_paise, snapshot.now_ns,
                                snapshot.observation ? snapshot.observation->cumulative_volume : 0U});
    } else if (intent.action == IntentAction::Modify) {
      mutation = broker_.modify({order_id, *intent.quantity, *intent.limit_price_paise});
    } else {
      mutation = broker_.cancel(order_id);
    }
  } catch (const std::exception&) {
    mutation = {BrokerMutationStatus::Ambiguous, order_id, std::nullopt, "proxy",
                BrokerError{"broker_exception", std::nullopt,
                            stable_uuid(intent.intent_id + ":exception")}};
  }
  if (!valid_mutation_result(mutation, order_id)) {
    mutation = {BrokerMutationStatus::Ambiguous, order_id, std::nullopt, "proxy",
                BrokerError{"broker_error_unclassified", std::nullopt,
                            stable_uuid(intent.intent_id + ":invalid-result")}};
  }
  bool outcome_ambiguous = mutation.status == BrokerMutationStatus::Ambiguous;
  std::string outcome_type;
  JsonObject outcome_payload;
  const std::string update_id = mutation.broker_correlation_id.value_or(
      stable_uuid(intent.intent_id + ":broker-outcome"));
  if (mutation.status == BrokerMutationStatus::Acknowledged && intent.action == IntentAction::Place &&
      mutation.broker_correlation_id) {
    outcome_type = "broker_acknowledged";
    outcome_payload = {{"broker_order_id", text(*mutation.broker_correlation_id)},
                       {"update_id", text(update_id)}};
  } else if (mutation.status == BrokerMutationStatus::Acknowledged &&
             intent.action == IntentAction::Modify &&
             mutation.accepted_quantity == intent.quantity &&
             mutation.accepted_limit_price_paise == intent.limit_price_paise) {
    outcome_type = "modified";
    outcome_payload = {{"limit_price_paise", integer(*intent.limit_price_paise)},
                       {"quantity", integer(*intent.quantity)},
                       {"update_id", text(update_id)}};
  } else if (mutation.status == BrokerMutationStatus::Acknowledged &&
             intent.action == IntentAction::Cancel && mutation.terminal_state_confirmed) {
    outcome_type = "cancelled";
    outcome_payload = {{"update_id", text(update_id)}};
  } else if (mutation.status == BrokerMutationStatus::Rejected) {
    outcome_type = intent.action == IntentAction::Modify
                       ? "modify_rejected"
                       : intent.action == IntentAction::Cancel ? "cancel_rejected" : "broker_rejected";
    outcome_payload = {{"error_code", text(bounded_broker_error(mutation.error))},
                       {"update_id", text(update_id)}};
  } else {
    outcome_ambiguous = true;
    outcome_type = "ambiguous_submission";
    outcome_payload = {{"error_code", text(mutation.error ? bounded_broker_error(mutation.error)
                                                           : "broker_outcome_uncertain")},
                       {"update_id", text(update_id)}};
  }
  mutation.broker_correlation_id = update_id;
  if (outcome_type == "broker_acknowledged")
    mutation.broker_correlation_id = json_string(outcome_payload.at("broker_order_id"),
                                                 "broker_order_id");
  if (outcome_type == "modify_rejected" || outcome_type == "cancel_rejected" ||
      outcome_type == "broker_rejected" || outcome_type == "ambiguous_submission") {
    const auto error_code = json_string(outcome_payload.at("error_code"), "error_code");
    mutation.error = BrokerError{error_code, std::nullopt, update_id};
  }
  outcome_payload.emplace("source_fingerprint", text(mutation_fingerprint(mutation)));
  outcome_payload.emplace("source_provenance", text(mutation.provenance));
  outcome_payload.emplace("source_sequence", integer(0U));
  OrderUpdateEvidence outcome_evidence;
  outcome_evidence.update_id = update_id;
  if (outcome_type == "broker_acknowledged") {
    outcome_evidence.kind = OrderEventKind::BrokerAcknowledged;
    outcome_evidence.broker_order_id = mutation.broker_correlation_id;
  } else if (outcome_type == "modified") {
    outcome_evidence.kind = OrderEventKind::ModifyAccepted;
    outcome_evidence.accepted_quantity = mutation.accepted_quantity;
    outcome_evidence.accepted_limit_price_paise = mutation.accepted_limit_price_paise;
  } else if (outcome_type == "cancelled") {
    outcome_evidence.kind = OrderEventKind::CancelAccepted;
  } else if (outcome_type == "modify_rejected") {
    outcome_evidence.kind = OrderEventKind::ModifyRejected;
  } else if (outcome_type == "cancel_rejected") {
    outcome_evidence.kind = OrderEventKind::CancelRejected;
  } else if (outcome_type == "broker_rejected") {
    outcome_evidence.kind = OrderEventKind::BrokerRejected;
  } else {
    outcome_evidence.kind = OrderEventKind::SubmissionAmbiguous;
  }
  const auto current_order = reconstructed_state_.orders.find(order_id);
  auto outcome_transition = current_order == reconstructed_state_.orders.end()
                                ? TransitionResult{}
                                : apply_order_update(current_order->second, outcome_evidence);
  if (current_order == reconstructed_state_.orders.end() || outcome_transition.error_code) {
    force_safety_stop(outcome_transition.error_code.value_or("outcome_order_missing"),
                      &intent, order_id);
    outcome_ambiguous = true;
  }
  const bool outcome_durable = durable_event(
      event_for(&intent, outcome_type, order_id, std::move(outcome_payload))) ==
      LedgerDurabilityBoundary::Durable;
  const bool outcome_acknowledged =
      !stage_coordinator_ ||
      stage_coordinator_->acknowledge_ledger_boundary(ledger_.last_sequence(), true);
  if (!outcome_durable || !outcome_acknowledged || outcome_ambiguous) {
    force_safety_stop("broker_outcome_uncertain", &intent, order_id);
    idempotency_store_.update(intent.intent_id, "ambiguous_submission", order_id, true);
    replayed_intent.disposition = "ambiguous_submission";
    replayed_intent.ambiguous = true;
  } else {
    reconstructed_state_.orders[order_id] = outcome_transition.aggregate;
    if (outcome_type == "broker_acknowledged") {
      replayed_state_.orders.push_back(
          {order_id, resolution.record->canonical_instrument_id,
           resolution.record->instrument_token, *intent.side, *intent.quantity,
           *intent.limit_price_paise, 0U, "working", mutation.provenance});
    } else {
      const auto replayed_order = std::find_if(
          replayed_state_.orders.begin(), replayed_state_.orders.end(),
          [&](const BrokerOrderSnapshot& item) { return item.internal_order_id == order_id; });
      if (replayed_order != replayed_state_.orders.end()) {
        if (outcome_type == "modified") {
          replayed_order->quantity = *intent.quantity;
          replayed_order->limit_price_paise = *intent.limit_price_paise;
        } else if (outcome_type == "cancelled") {
          replayed_order->state = "cancelled";
        }
      }
    }
    idempotency_store_.update(intent.intent_id, outcome_type, order_id, false);
    replayed_intent.disposition = outcome_type;
    replayed_intent.ambiguous = false;
  }
  SessionIntentResult result{decision, mutation, false, safety_stopped_};
  outcomes_.emplace(intent.intent_id, std::pair{fingerprint, result});
  return result;
}

SessionIntentResult ExecutionSession::accept_intent(const OrderIntent& intent) {
  return submit_prepared(prepare_intent(intent));
}

bool ExecutionSession::accept_broker_update(const BrokerUpdateEnvelope& update) {
  if (!enqueue_broker_update(update)) return false;
  return drain_broker_updates();
}

bool ExecutionSession::enqueue_broker_update(BrokerUpdateEnvelope update) {
  if (update.update_id.empty()) return false;
  if (const auto found = applied_update_fingerprints_.find(update.update_id);
      found != applied_update_fingerprints_.end()) {
    if (found->second == update_fingerprint(update)) return true;
    force_safety_stop("broker_update_conflicting_duplicate");
    return false;
  }
  const auto queued = std::find_if(update_queue_.begin(), update_queue_.end(),
                                   [&](const BrokerUpdateEnvelope& item) {
                                     return item.update_id == update.update_id;
                                   });
  if (queued != update_queue_.end()) {
    if (update_fingerprint(*queued) == update_fingerprint(update)) return true;
    force_safety_stop("broker_update_conflicting_duplicate");
    return false;
  }
  if (update.session_lost || update.sequence <= last_update_sequence_ ||
      update_queue_.size() >= maximum_update_queue_) {
    activate_kill_switch(update.session_lost ? "broker_session_lost" : "broker_update_queue_fault");
    reconciliation_required_ = true;
    return false;
  }
  update_queue_.push_back(std::move(update));
  return true;
}

bool ExecutionSession::drain_broker_updates() {
  while (!update_queue_.empty()) {
    auto update = std::move(update_queue_.front());
    update_queue_.pop_front();
    if (update.sequence <= last_update_sequence_) {
      activate_kill_switch("broker_update_sequence_fault");
      reconciliation_required_ = true;
      return false;
    }
    const auto order = reconstructed_state_.orders.find(update.internal_order_id);
    const auto intent = reconstructed_state_.intents.find(update.intent_id);
    if (order == reconstructed_state_.orders.end() || intent == reconstructed_state_.intents.end() ||
        intent->second.internal_order_id != update.internal_order_id || !bound_strategy_id_ ||
        update.strategy_id != *bound_strategy_id_ ||
        update.strategy_run_id != *bound_strategy_run_id_ ||
        intent->second.strategy_id != update.strategy_id ||
        intent->second.strategy_run_id != update.strategy_run_id ||
        !is_canonical_uuid(update.strategy_run_id) || !is_canonical_uuid(update.intent_id)) {
      force_safety_stop("broker_update_unknown_correlation");
      return false;
    }
    OrderUpdateEvidence evidence{update.kind, update.update_id, update.broker_order_id,
                                 update.cumulative_filled_quantity, update.accepted_quantity,
                                 update.accepted_limit_price_paise};
    const auto transition = apply_order_update(order->second, evidence);
    if (transition.error_code) {
      force_safety_stop(*transition.error_code);
      return false;
    }
    OrderIntent correlation;
    correlation.intent_id = update.intent_id;
    correlation.strategy_id = update.strategy_id;
    correlation.strategy_run_id = update.strategy_run_id;
    correlation.execution_session_id = execution_session_id_;
    std::string event_type;
    const auto fingerprint = update_fingerprint(update);
    JsonObject payload{{"source_fingerprint", text(fingerprint)},
                       {"source_provenance", text(update.provenance.value_or("broker_confirmed"))},
                       {"source_sequence", integer(update.sequence)},
                       {"update_id", text(update.update_id)}};
    switch (update.kind) {
      case OrderEventKind::BrokerAcknowledged:
        event_type = "broker_acknowledged";
        if (!update.broker_order_id) { force_safety_stop("broker_update_missing_order_id"); return false; }
        payload.emplace("broker_order_id", text(*update.broker_order_id));
        break;
      case OrderEventKind::FillUpdate:
        event_type = transition.aggregate.state == OrderState::Filled ? "filled" : "partially_filled";
        if (!update.cumulative_filled_quantity) { force_safety_stop("broker_update_missing_fill"); return false; }
        payload.emplace("cumulative_filled_quantity", integer(*update.cumulative_filled_quantity));
        if (!update.fill_price_paise || !update.provenance || !update.evidence_timestamp_ns ||
            *update.evidence_timestamp_ns < 0 ||
            (*update.provenance != "simulated_proxy" && *update.provenance != "simulated" &&
             *update.provenance != "proxy" && *update.provenance != "broker_confirmed")) {
          force_safety_stop("broker_update_missing_fill_evidence"); return false;
        }
        payload.emplace("fill_price_paise", integer(*update.fill_price_paise));
        payload.emplace("evidence_timestamp_ns",
                        JsonValue(JsonInteger{
                            std::to_string(*update.evidence_timestamp_ns)}));
        payload.emplace("provenance", text(*update.provenance == "simulated_proxy"
                                                ? "simulated" : *update.provenance));
        break;
      case OrderEventKind::ModifyAccepted:
        event_type = "modified";
        if (!update.accepted_quantity || !update.accepted_limit_price_paise) {
          force_safety_stop("broker_update_missing_modify_terms"); return false;
        }
        payload.emplace("quantity", integer(*update.accepted_quantity));
        payload.emplace("limit_price_paise", integer(*update.accepted_limit_price_paise));
        break;
      case OrderEventKind::ModifyRejected:
        event_type = "modify_rejected";
        payload.emplace("error_code", text(bounded_broker_error(BrokerError{
            update.error_code.value_or("broker_rejected"), std::nullopt, update.update_id})));
        break;
      case OrderEventKind::CancelAccepted: event_type = "cancelled"; break;
      case OrderEventKind::CancelRejected:
        event_type = "cancel_rejected";
        payload.emplace("error_code", text(bounded_broker_error(BrokerError{
            update.error_code.value_or("broker_rejected"), std::nullopt, update.update_id})));
        break;
      case OrderEventKind::SubmissionAmbiguous:
        event_type = "ambiguous_submission";
        payload.emplace("error_code", text(bounded_broker_error(BrokerError{
            update.error_code.value_or("broker_outcome_uncertain"), std::nullopt,
            update.update_id})));
        break;
      case OrderEventKind::BrokerRejected:
        event_type = "broker_rejected";
        payload.emplace("error_code", text(bounded_broker_error(BrokerError{
            update.error_code.value_or("broker_rejected"), std::nullopt, update.update_id})));
        break;
      default:
        force_safety_stop("broker_update_kind_not_external");
        return false;
    }
    if (durable_event(event_for(&correlation, event_type, update.internal_order_id,
                                std::move(payload))) != LedgerDurabilityBoundary::Durable) return false;
    last_update_sequence_ = update.sequence;
    next_local_update_sequence_ = std::max(next_local_update_sequence_, update.sequence);
    reconstructed_state_.last_broker_update_sequence = update.sequence;
    reconstructed_state_.broker_update_fingerprints.insert_or_assign(update.update_id,
                                                                      fingerprint);
    order->second = transition.aggregate;
    const auto replayed_order = std::find_if(
        replayed_state_.orders.begin(), replayed_state_.orders.end(),
        [&](const BrokerOrderSnapshot& item) {
          return item.internal_order_id == update.internal_order_id;
        });
    if (replayed_order == replayed_state_.orders.end()) {
      force_safety_stop("broker_update_missing_replayed_order");
      return false;
    }
    replayed_order->quantity = transition.aggregate.effective_quantity;
    replayed_order->limit_price_paise = transition.aggregate.limit_price_paise;
    replayed_order->cumulative_filled_quantity = transition.aggregate.cumulative_filled_quantity;
    replayed_order->state = order_state_name(transition.aggregate.state);
    if (replayed_order->state == "acknowledged") replayed_order->state = "working";
    if (transition.signed_position_delta != 0) {
      reconstructed_state_.positions[order->second.canonical_instrument_id] +=
          transition.signed_position_delta;
      const auto token = reconstructed_state_.order_route_tokens.find(update.internal_order_id);
      if (token != reconstructed_state_.order_route_tokens.end())
        reconstructed_state_.route_positions[token->second] += transition.signed_position_delta;
      replayed_state_.fills.push_back(
          {update.update_id,
           update.internal_order_id, replayed_order->canonical_instrument_id,
           replayed_order->instrument_token, *update.cumulative_filled_quantity,
           static_cast<std::uint64_t>(transition.signed_position_delta < 0
                                          ? -transition.signed_position_delta
                                          : transition.signed_position_delta),
           *update.fill_price_paise, *update.evidence_timestamp_ns,
           update.provenance.value_or("proxy")});
      const auto position = std::find_if(
          replayed_state_.positions.begin(), replayed_state_.positions.end(),
          [&](const BrokerPositionSnapshot& item) {
            return item.canonical_instrument_id == replayed_order->canonical_instrument_id;
          });
      if (position == replayed_state_.positions.end()) {
        replayed_state_.positions.push_back(
            {replayed_order->canonical_instrument_id, replayed_order->instrument_token,
             transition.signed_position_delta, update.provenance.value_or("proxy")});
      } else {
        position->quantity += transition.signed_position_delta;
      }
    }
    applied_update_fingerprints_.emplace(update.update_id, update_fingerprint(update));
  }
  return true;
}

void ExecutionSession::activate_kill_switch(std::string reason) {
  force_safety_stop(std::move(reason));
}

bool ExecutionSession::reconcile_after_strategy_reconnect() {
  if (!started_ || stopping_ || (!safety_stopped_ && !reconciliation_required_)) return false;
  ReconciliationResult result;
  try {
    result = reconciler_.compare(
        replayed_state_, broker_.query_orders(), broker_.query_trades(), broker_.query_positions(),
        execution_session_id_, stable_uuid(execution_session_id_ + ":strategy-reconnect"),
        clock_.now_ns());
  } catch (const std::exception&) {
    force_safety_stop("strategy_reconnect_reconciliation_exception");
    return false;
  }
  if (!result.exact_agreement || broker_.session_health() != BrokerSessionHealth::Ready) {
    force_safety_stop(result.incidents.empty() ? "strategy_reconnect_broker_not_ready"
                                               : result.incidents.front());
    return false;
  }
  if (durable_event(event_for(nullptr, "reconciliation_completed", std::nullopt,
                              {{"reason", text("strategy_reconnect_exact")}})) !=
      LedgerDurabilityBoundary::Durable)
    return false;
  kill_switch_ = false;
  safety_stopped_ = false;
  reconciliation_required_ = false;
  reconstructed_state_.safety_stopped = false;
  reconstructed_state_.reconciliation_required = false;
  reconstructed_state_.global_reconciliation_required = false;
  ++authority_generation_;
  return !observation_ || activate();
}

SessionStopResult ExecutionSession::stop(
    std::optional<std::chrono::steady_clock::time_point> deadline) {
  SessionStopResult result;
  ++authority_generation_;
  stopping_ = true; ready_ = false; kill_switch_ = true;
  if (durable_event(event_for(nullptr, "session_stopping", std::nullopt,
                              {{"state", text("stopping")}})) !=
      LedgerDurabilityBoundary::Durable) return result;
  if (!broker_.shutdown_operations_bounded_nonblocking()) {
    reconciliation_required_ = true;
    safety_stopped_ = true;
    result.ledger_flushed = ledger_.flush();
    if (result.ledger_flushed)
      result.stopped_recorded = durable_event(event_for(
          nullptr, "session_stopped", std::nullopt,
          {{"reason", text("shutdown_adapter_unbounded")},
           {"state", text("uncertain")}})) == LedgerDurabilityBoundary::Durable;
    started_ = false;
    return result;
  }
  BrokerQueryResult<BrokerOrderSnapshot> orders;
  try {
    orders = broker_.query_orders();
  } catch (const std::exception&) {
    force_safety_stop("shutdown_order_query_exception");
    return result;
  }
  if (orders.authoritative()) {
    std::uint64_t shutdown_broker_calls = 0U;
    std::size_t accounted_working_orders = 0U;
    for (const auto& order : orders.items) {
      if (!working_state(order.state)) continue;
      ++result.working_orders_seen;
      OrderIntent shutdown_cancel;
      shutdown_cancel.intent_id = stable_uuid(execution_session_id_ + ":shutdown:" +
                                              order.internal_order_id);
      shutdown_cancel.strategy_id = bound_strategy_id_.value_or("session_shutdown");
      shutdown_cancel.strategy_run_id = bound_strategy_run_id_.value_or(
          stable_uuid(execution_session_id_ + ":shutdown-run"));
      shutdown_cancel.execution_session_id = execution_session_id_;
      shutdown_cancel.created_at_ns = clock_.now_ns();
      shutdown_cancel.canonical_instrument_id = order.canonical_instrument_id;
      shutdown_cancel.action = IntentAction::Cancel;
      shutdown_cancel.target_internal_order_id = order.internal_order_id;
      const auto refuse_unattempted = [&](std::string reason) {
        reconciliation_required_ = true;
        safety_stopped_ = true;
        if (durable_event(event_for(
                &shutdown_cancel, "reconciliation_required", order.internal_order_id,
                {{"reason", text(std::move(reason))}})) ==
            LedgerDurabilityBoundary::Durable) {
          ++result.cancellation_refusals;
          ++accounted_working_orders;
        }
      };
      if (shutdown_cancel.created_at_ns == std::numeric_limits<std::int64_t>::max()) {
        refuse_unattempted("shutdown_cancel_clock_overflow");
        continue;
      }
      shutdown_cancel.expires_at_ns = shutdown_cancel.created_at_ns + 1;
      const bool deadline_exhausted = deadline && std::chrono::steady_clock::now() >= *deadline;
      const bool rate_exhausted =
          shutdown_broker_calls >= risk_engine_.configuration().maximum_orders_per_window;
      if (deadline_exhausted || rate_exhausted) {
        const std::string reason = deadline_exhausted
                                       ? "shutdown_cancel_unattempted_deadline"
                                       : "shutdown_cancel_unattempted_rate_limit";
        refuse_unattempted(reason);
        continue;
      }
      if (durable_event(event_for(&shutdown_cancel, "intent_received", std::nullopt,
                                  {{"canonical_instrument_id", text(order.canonical_instrument_id)},
                                   {"semantic_fingerprint",
                                    text(shutdown_cancel.semantic_fingerprint())}})) !=
          LedgerDurabilityBoundary::Durable) {
        refuse_unattempted("shutdown_cancel_intent_not_durable");
        continue;
      }
      ResolutionResult route;
      try {
        route = resolver_.resolve(order.canonical_instrument_id);
      } catch (const std::exception&) {
        refuse_unattempted("shutdown_cancel_mapping_exception");
        continue;
      }
      if (!route.record) {
        refuse_unattempted("shutdown_cancel_mapping_unavailable");
        continue;
      }
      if (durable_event(event_for(
              &shutdown_cancel, "mapping_validated", order.internal_order_id,
              {{"exchange_segment", text(route.record->exchange_segment)},
               {"instrument_token", text(route.record->instrument_token)},
               {"lot_size", integer(route.record->lot_size)},
               {"routing_snapshot_digest", text(std::string(resolver_.snapshot_digest()))},
               {"tick_size_paise", integer(route.record->tick_size_paise)},
               {"trading_symbol", text(route.record->trading_symbol)}})) !=
          LedgerDurabilityBoundary::Durable) {
        refuse_unattempted("shutdown_cancel_mapping_not_durable");
        continue;
      }
      RiskSnapshot shutdown_snapshot;
      try {
        shutdown_snapshot = capture_risk_snapshot(shutdown_cancel, route);
      } catch (const std::exception&) {
        refuse_unattempted("shutdown_cancel_snapshot_unavailable");
        continue;
      }
      RiskDecision shutdown_decision;
      try {
        if (stage_coordinator_) stage_coordinator_->before_shutdown_risk_evaluation();
        shutdown_decision = risk_engine_.evaluate(shutdown_cancel, shutdown_snapshot);
      } catch (const std::exception&) {
        refuse_unattempted("shutdown_cancel_risk_exception");
        continue;
      }
      if (!risk_approved(shutdown_decision)) {
        refuse_unattempted("shutdown_cancel_risk_refused");
        continue;
      }
      if (durable_event(event_for(
              &shutdown_cancel, "risk_approved", order.internal_order_id,
              {{"broker_call_count", integer(0U)},
               {"configuration_digest", text(shutdown_decision.configuration_digest)},
               {"decision_id", text(shutdown_decision.decision_id)},
               {"risk_decision", parse_json(shutdown_decision.to_json())}})) !=
          LedgerDurabilityBoundary::Durable) {
        refuse_unattempted("shutdown_cancel_risk_not_durable");
        continue;
      }
      if (durable_event(event_for(&shutdown_cancel, "cancel_requested", order.internal_order_id,
                                  {{"update_id", text(stable_uuid(
                                      shutdown_cancel.intent_id + ":cancel-request"))}})) !=
          LedgerDurabilityBoundary::Durable) {
        refuse_unattempted("shutdown_cancel_request_not_durable");
        continue;
      }
      bool boundary_acknowledged = true;
      try {
        boundary_acknowledged = !stage_coordinator_ ||
            stage_coordinator_->acknowledge_ledger_boundary(ledger_.last_sequence(), false);
      } catch (const std::exception&) {
        boundary_acknowledged = false;
      }
      if (!boundary_acknowledged) {
        refuse_unattempted("shutdown_cancel_boundary_not_acknowledged");
        continue;
      }
      BrokerMutationResult cancelled;
      ++shutdown_broker_calls;
      ++result.cancellation_attempts;
      try {
        cancelled = broker_.cancel(order.internal_order_id);
      } catch (const std::exception&) {
        cancelled = {BrokerMutationStatus::Ambiguous, order.internal_order_id, std::nullopt,
                     "proxy", BrokerError{"broker_exception", std::nullopt,
                                           stable_uuid(shutdown_cancel.intent_id + ":exception")}};
      }
      if (!valid_mutation_result(cancelled, order.internal_order_id)) {
        cancelled = {BrokerMutationStatus::Ambiguous, order.internal_order_id, std::nullopt,
                     "proxy", BrokerError{"broker_error_unclassified", std::nullopt,
                                            stable_uuid(shutdown_cancel.intent_id +
                                                        ":invalid-result")}};
      }
      result.cancel_results.push_back(cancelled);
      const bool confirmed = cancelled.status == BrokerMutationStatus::Acknowledged &&
                             cancelled.terminal_state_confirmed;
      const std::string outcome = confirmed
                                      ? "cancelled"
                                      : cancelled.status == BrokerMutationStatus::Rejected
                                            ? "cancel_rejected" : "ambiguous_submission";
      JsonObject payload{{"update_id", text(cancelled.broker_correlation_id.value_or(
          stable_uuid(shutdown_cancel.intent_id + ":outcome")))}};
      if (!confirmed)
        payload.emplace("error_code", text(bounded_broker_error(cancelled.error)));
      payload.emplace("source_fingerprint", text(mutation_fingerprint(cancelled)));
      payload.emplace("source_provenance", text(cancelled.provenance));
      payload.emplace("source_sequence", integer(0U));
      const bool outcome_durable =
          durable_event(event_for(&shutdown_cancel, outcome, order.internal_order_id,
                                  std::move(payload))) == LedgerDurabilityBoundary::Durable;
      if (outcome_durable) ++accounted_working_orders;
      bool outcome_acknowledged = true;
      try {
        outcome_acknowledged = !stage_coordinator_ ||
            stage_coordinator_->acknowledge_ledger_boundary(ledger_.last_sequence(), true);
      } catch (const std::exception&) {
        outcome_acknowledged = false;
      }
      if (!outcome_durable || !outcome_acknowledged || !confirmed) {
        reconciliation_required_ = true; safety_stopped_ = true;
        if (!outcome_durable)
          refuse_unattempted("shutdown_cancel_outcome_not_durable");
      } else {
        const auto replayed_order = std::find_if(
            replayed_state_.orders.begin(), replayed_state_.orders.end(),
            [&](const BrokerOrderSnapshot& item) {
              return item.internal_order_id == order.internal_order_id;
            });
        if (replayed_order != replayed_state_.orders.end()) replayed_order->state = "cancelled";
      }
    }
    result.cancellation_accounting_complete =
        accounted_working_orders == result.working_orders_seen;
  } else {
    reconciliation_required_ = true; safety_stopped_ = true;
  }
  result.cancellation_complete = orders.authoritative() &&
      result.cancellation_accounting_complete &&
      result.cancellation_refusals == 0U &&
      result.cancellation_attempts == result.working_orders_seen &&
      std::all_of(result.cancel_results.begin(), result.cancel_results.end(),
                  [](const BrokerMutationResult& mutation) {
                    return mutation.status == BrokerMutationStatus::Acknowledged &&
                           mutation.terminal_state_confirmed;
                  });
  ReconciliationResult reconciliation;
  bool broker_ready_after_queries = false;
  if (!deadline || std::chrono::steady_clock::now() < *deadline) {
    try {
      const auto reconciliation_orders = broker_.query_orders();
      const auto reconciliation_trades = broker_.query_trades();
      const auto reconciliation_positions = broker_.query_positions();
      broker_ready_after_queries =
          broker_.session_health() == BrokerSessionHealth::Ready;
      if (!broker_ready_after_queries) throw std::runtime_error("shutdown_broker_not_ready");
      reconciliation = reconciler_.compare(
          replayed_state_, reconciliation_orders, reconciliation_trades,
          reconciliation_positions,
          execution_session_id_, stable_uuid(execution_session_id_ + ":shutdown"), clock_.now_ns());
    } catch (const std::exception&) {
      force_safety_stop("shutdown_reconciliation_exception");
    }
  }
  result.reconciliation_exact = result.cancellation_complete && broker_ready_after_queries &&
                                reconciliation.exact_agreement;
  if (!result.reconciliation_exact) { reconciliation_required_ = true; safety_stopped_ = true; }
  result.ledger_flushed = ledger_.flush();
  if (result.ledger_flushed)
    result.stopped_recorded = durable_event(event_for(
        nullptr, "session_stopped", std::nullopt,
        {{"state", text(result.reconciliation_exact ? "reconciled" : "uncertain")}})) ==
        LedgerDurabilityBoundary::Durable;
  started_ = false;
  return result;
}

}  // namespace shaurya::execution
