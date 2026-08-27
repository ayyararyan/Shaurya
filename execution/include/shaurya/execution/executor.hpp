#pragma once

#include "shaurya/execution/execution_ledger.hpp"
#include "shaurya/execution/execution_session.hpp"
#include "shaurya/execution/ipc_protocol.hpp"
#include "shaurya/execution/ipc_transport.hpp"
#include "shaurya/execution/paper_broker.hpp"

#include <array>
#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <chrono>
#include <deque>
#include <filesystem>
#include <future>
#include <iosfwd>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <vector>
#include <utility>
#include <variant>

namespace shaurya::execution {

enum class ExecutorQueueKind : std::size_t {
  MarketReceive, StrategyReceive, RiskWork, BrokerSubmission,
  BrokerUpdate, LedgerCommand, OutboundEvent, Count
};

struct QueueMetrics { std::size_t depth{}; std::size_t high_water{}; std::size_t capacity{}; };

template <typename T>
class BoundedChannel {
 public:
  explicit BoundedChannel(std::size_t capacity) : capacity_(capacity) {
    if (capacity == 0U) throw std::invalid_argument("queue_capacity_invalid");
  }
  [[nodiscard]] bool try_push(T value) {
    const std::lock_guard<std::mutex> guard(*mutex_);
    if (items_.size() >= capacity_) return false;
    items_.push_back(std::move(value));
    if (items_.size() > high_water_) high_water_ = items_.size();
    return true;
  }
  [[nodiscard]] std::optional<T> try_pop() {
    const std::lock_guard<std::mutex> guard(*mutex_);
    if (items_.empty()) return std::nullopt;
    T result = std::move(items_.front()); items_.pop_front(); return result;
  }
  [[nodiscard]] bool try_replace_front(T value) {
    const std::lock_guard<std::mutex> guard(*mutex_);
    if (items_.empty()) return false;
    items_.front() = std::move(value);
    return true;
  }
  template <typename Predicate>
  [[nodiscard]] bool try_replace_first_if(Predicate predicate, T value) {
    const std::lock_guard<std::mutex> guard(*mutex_);
    const auto found = std::find_if(items_.begin(), items_.end(), predicate);
    if (found == items_.end()) return false;
    *found = std::move(value);
    return true;
  }
  template <typename Predicate>
  [[nodiscard]] bool discard_front_if(Predicate predicate) {
    const std::lock_guard<std::mutex> guard(*mutex_);
    if (items_.empty() || !predicate(items_.front())) return false;
    items_.pop_front(); return true;
  }
  template <typename Predicate>
  [[nodiscard]] std::size_t discard_all_if(Predicate predicate) {
    const std::lock_guard<std::mutex> guard(*mutex_);
    const auto before = items_.size();
    std::erase_if(items_, predicate);
    return before - items_.size();
  }
  template <typename Predicate>
  [[nodiscard]] bool front_satisfies(Predicate predicate) const {
    const std::lock_guard<std::mutex> guard(*mutex_);
    return !items_.empty() && predicate(items_.front());
  }
  [[nodiscard]] QueueMetrics metrics() const noexcept {
    const std::lock_guard<std::mutex> guard(*mutex_);
    return {items_.size(), high_water_, capacity_};
  }
 private:
  std::size_t capacity_{}; std::size_t high_water_{}; std::deque<T> items_;
  std::shared_ptr<std::mutex> mutex_{std::make_shared<std::mutex>()};
};

struct ExecutorConfiguration {
  std::string schema_version{"1.0.0"};
  std::string configuration_version;
  std::string configuration_digest;
  std::string mode;
  std::string trading_date;
  std::filesystem::path runtime_directory;
  std::filesystem::path protected_artifact_root;
  std::shared_ptr<int> protected_artifact_descriptor;
  std::string market_socket_basename;
  std::string strategy_socket_basename;
  std::size_t maximum_packet_bytes{};
  std::array<std::size_t, static_cast<std::size_t>(ExecutorQueueKind::Count)> queue_capacities{};
  std::int64_t io_deadline_ms{};
  std::int64_t reconnect_window_ms{};
  std::int64_t shutdown_deadline_ms{};
  std::string execution_session_id;
  std::string expected_strategy_id;
  std::filesystem::path routing_snapshot;
  std::filesystem::path routing_manifest;
  std::filesystem::path ledger_path;
  std::filesystem::path launch_attestation_root;
  std::shared_ptr<int> launch_attestation_root_descriptor;
  std::string expected_cli_release_digest;
  std::string expected_deployment_manifest_digest;
  std::string expected_executor_build_digest;
  std::int64_t maximum_launch_attestation_age_ns{};
  std::filesystem::path risk_configuration_path;
  std::filesystem::path paper_model_path;
  std::int64_t required_initial_observation_freshness_ns{};
  ExpectedPeerIdentity market_peer_identity;
  ExpectedPeerIdentity strategy_peer_identity;
  std::filesystem::path market_peer_configuration_path;
  std::filesystem::path strategy_peer_configuration_path;
};

struct MarketAcceptResult {
  std::optional<IpcEnvelope> strategy_book;
  std::vector<IpcEnvelope> execution_events;
};

struct PaperBrokerRecovery {
  ReplayedBrokerState replayed;
  PaperBrokerSnapshot snapshot;
};

struct DurableLedgerCommand {
  std::uint64_t expected_sequence{};
  bool broker_attempted{};
  std::shared_ptr<std::promise<bool>> acknowledgement;
};

struct BrokerUpdateReservation { std::uint64_t ordinal{}; };

using ExecutorStageMessage =
    std::variant<IpcEnvelope, BrokerUpdateEnvelope, DurableLedgerCommand,
                 BrokerUpdateReservation, PreparedSessionIntent>;

[[nodiscard]] PaperBrokerRecovery recover_paper_broker(
    const LedgerVerificationResult& verification,
    PaperFillModel model = PaperFillModel::D51ProxyV1);

[[nodiscard]] ExecutorConfiguration parse_executor_configuration(std::string_view bytes);
[[nodiscard]] ExecutorConfiguration load_executor_configuration(const std::filesystem::path& path);
[[nodiscard]] std::string running_executable_digest();

[[nodiscard]] SessionLaunchEvidence validate_launch_attestation(
    const ExecutorConfiguration& configuration, const std::filesystem::path& path,
    std::int64_t now_ns);

class Executor : public SessionStageCoordinator {
 public:
  Executor(ExecutorConfiguration configuration, ExecutionSession& session,
           ExecutionLedger& durable_event_ledger, SessionClock& clock);
  ~Executor();
  void authenticate_peer(const ExpectedPeerIdentity& expected,
                         const IpcHandshake& handshake,
                         const PeerInspector& inspector,
                         int accepted_socket,
                         bool production_required = true);
  void validate_peer_connection(PeerRole role, const PeerInspector& inspector,
                                int accepted_socket) const;
  [[nodiscard]] MarketAcceptResult accept_market(IpcEnvelope envelope);
  [[nodiscard]] std::vector<IpcEnvelope> accept_intent(IpcEnvelope envelope);
  [[nodiscard]] bool submit_market_from_reader(IpcEnvelope envelope);
  [[nodiscard]] bool submit_intent_from_reader(IpcEnvelope envelope);
  [[nodiscard]] MarketAcceptResult process_next_market();
  [[nodiscard]] std::vector<IpcEnvelope> process_next_intent();
  [[nodiscard]] std::vector<IpcEnvelope> process_next_risk_work();
  [[nodiscard]] std::vector<IpcEnvelope> process_next_broker_submission();
  void record_reader_overflow(ExecutorQueueKind queue);
  void record_peer_disconnect(PeerRole role);
  [[nodiscard]] bool acknowledge_ledger_boundary(std::uint64_t expected_sequence,
                                                  bool broker_attempted) override;
  [[nodiscard]] bool reserve_broker_updates(std::size_t maximum_updates) override;
  [[nodiscard]] bool dispatch_broker_update(BrokerUpdateEnvelope update) override;
  void release_broker_update_reservations() noexcept override;
  [[nodiscard]] std::vector<ReplayEvent> reconnect(std::uint64_t after_event_sequence,
                                                   std::string_view session,
                                                   std::string_view strategy) const;
  void establish_acknowledgement_cursor(std::uint64_t event_sequence);
  void acknowledge_events_through(std::uint64_t event_sequence);
  void mark_event_delivered(std::uint64_t event_sequence);
  [[nodiscard]] bool enqueue(ExecutorQueueKind queue, IpcEnvelope envelope,
                             bool broker_attempted = false);
  void request_stop() noexcept;
  [[nodiscard]] bool stop_requested() const noexcept { return stop_requested_.load(); }
  [[nodiscard]] SessionStopResult shutdown();
  [[nodiscard]] bool shutdown_succeeded() const noexcept { return shutdown_succeeded_; }
  [[nodiscard]] std::chrono::steady_clock::time_point shutdown_deadline() const noexcept;
  [[nodiscard]] std::uint64_t last_delivered_event_sequence() const noexcept;
  [[nodiscard]] bool ready() const noexcept;
  [[nodiscard]] bool check_market_freshness();
  [[nodiscard]] bool restore_strategy_authority_after_reconnect();
  [[nodiscard]] bool next_market_is_safety_fault() const;
  [[nodiscard]] bool safety_stopped() const noexcept { return safety_reason_.has_value(); }
  [[nodiscard]] const std::optional<std::string>& safety_reason() const noexcept { return safety_reason_; }
  [[nodiscard]] QueueMetrics queue_metrics(ExecutorQueueKind queue) const;

 private:
  [[nodiscard]] std::vector<IpcEnvelope> collect_events_after(std::uint64_t sequence,
                                                               bool broker_attempted = false);
  [[nodiscard]] std::vector<IpcEnvelope> replay_intent(std::string_view intent_id) const;
  [[nodiscard]] std::optional<IpcEnvelope> pass_stage(ExecutorQueueKind queue,
                                                      IpcEnvelope envelope,
                                                      bool broker_attempted = false);
  void ledger_worker_loop();
  void stop_once(std::string reason);
  void update_shutdown_success_locked() noexcept;
  ExecutorConfiguration configuration_;
  ExecutionSession& session_;
  ExecutionLedger& durable_event_ledger_;
  SessionClock& clock_;
  std::array<BoundedChannel<ExecutorStageMessage>,
             static_cast<std::size_t>(ExecutorQueueKind::Count)> queues_;
  EventReplayLog replay_;
  bool market_authenticated_{};
  bool strategy_authenticated_{};
  bool fresh_observation_{};
  std::atomic<bool> stop_requested_{};
  std::uint64_t observation_sequence_{};
  std::uint64_t event_sequence_{};
  std::uint64_t last_acknowledged_event_sequence_{};
  std::uint64_t last_delivered_event_sequence_{};
  std::optional<std::int64_t> last_observation_receive_ns_;
  std::optional<std::chrono::steady_clock::time_point> last_observation_activity_;
  std::optional<std::string> safety_reason_;
  std::optional<SessionStopResult> shutdown_result_;
  std::optional<std::chrono::steady_clock::time_point> shutdown_deadline_;
  bool shutdown_core_succeeded_{};
  bool shutdown_succeeded_{};
  std::optional<PeerEvidence> market_peer_;
  std::optional<PeerEvidence> strategy_peer_;
  std::optional<std::string> bound_strategy_run_id_;
  mutable std::mutex state_mutex_;
  std::size_t reserved_broker_updates_{};
  bool broker_update_dispatched_in_cycle_{};
  std::atomic<bool> ledger_worker_stop_{};
  std::thread ledger_worker_;
};

class ExecutorServer {
 public:
  ExecutorServer(Executor& executor, ExecutorConfiguration configuration,
                 ExpectedPeerIdentity market_identity,
                 ExpectedPeerIdentity strategy_identity,
                 const PeerInspector& market_inspector,
                 const PeerInspector& strategy_inspector,
                 bool production_peer_validation = true);
  void run();
  void request_stop() noexcept { executor_.request_stop(); }
  [[nodiscard]] const std::filesystem::path& market_socket_path() const noexcept {
    return market_listener_.path();
  }
  [[nodiscard]] const std::filesystem::path& strategy_socket_path() const noexcept {
    return strategy_listener_.path();
  }

 private:
  [[nodiscard]] int accept_authenticated(ProtectedUnixListener& listener,
                                         PeerRole role,
                                         const ExpectedPeerIdentity& expected,
                                         const PeerInspector& inspector,
                                         std::optional<std::uint64_t>& replay_cursor,
                                         bool reconnect = false);
  Executor& executor_;
  ExecutorConfiguration configuration_;
  ExpectedPeerIdentity market_identity_;
  ExpectedPeerIdentity strategy_identity_;
  const PeerInspector& market_inspector_;
  const PeerInspector& strategy_inspector_;
  bool production_peer_validation_{};
  IpcSocketMode mode_{IpcSocketMode::Stream};
  IpcFrameCodec codec_;
  ProtectedUnixListener market_listener_;
  ProtectedUnixListener strategy_listener_;
  std::uint64_t nonce_sequence_{};
};

int executor_cli(const std::vector<std::string>& arguments, std::ostream& output,
                 std::ostream& error);

}  // namespace shaurya::execution
