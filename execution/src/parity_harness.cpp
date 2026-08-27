#include "shaurya/execution/parity_harness.hpp"

#include "shaurya/execution/build_attestation.hpp"
#include "shaurya/execution/canonical_json.hpp"
#include "shaurya/execution/execution_session.hpp"
#include "shaurya/execution/executor.hpp"
#include "shaurya/execution/ipc_protocol.hpp"
#include "shaurya/execution/paper_broker.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdint>
#include <fcntl.h>
#include <filesystem>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string_view>
#include <sys/stat.h>
#include <unistd.h>

#ifndef SHAURYA_PARITY_SCHEMA_DIGEST
#error "SHAURYA_PARITY_SCHEMA_DIGEST must bind the execution-event schema at configure time"
#endif
#ifndef SHAURYA_PARITY_CLIENT_CONTRACT_DIGEST
#error "SHAURYA_PARITY_CLIENT_CONTRACT_DIGEST must bind the aggregate client contract"
#endif

namespace shaurya::execution {
namespace {

constexpr std::size_t kMaximumFixtureBytes = 4U * 1024U * 1024U;

[[noreturn]] void refuse(std::string code) { throw std::runtime_error(std::move(code)); }
JsonValue text(std::string value) { return JsonValue(std::move(value)); }
JsonValue number(std::uint64_t value) { return JsonValue(JsonInteger{std::to_string(value)}); }
JsonValue number(std::int64_t value) { return JsonValue(JsonInteger{std::to_string(value)}); }
const JsonValue& required(const JsonObject& object, std::string_view key) {
  const auto found = object.find(key);
  if (found == object.end()) refuse("fixture_missing_field");
  return found->second;
}
void exact(const JsonObject& object, std::initializer_list<std::string_view> fields) {
  if (object.size() != fields.size()) refuse("fixture_unknown_or_missing_field");
  for (const auto field : fields)
    if (!object.contains(field)) refuse("fixture_missing_field");
}
std::string string_field(const JsonObject& object, std::string_view key,
                         std::size_t maximum = 192U) {
  try {
    const auto& value = json_string(required(object, key), key);
    if (value.empty() || value.size() > maximum) refuse("fixture_invalid_string");
    return value;
  } catch (const JsonError&) { refuse("fixture_invalid_field"); }
}
std::uint64_t uint_field(const JsonObject& object, std::string_view key) {
  try { return json_uint64(required(object, key), key); }
  catch (const JsonError&) { refuse("fixture_invalid_field"); }
}
std::int64_t int_field(const JsonObject& object, std::string_view key) {
  try { return json_int64(required(object, key), key); }
  catch (const JsonError&) { refuse("fixture_invalid_field"); }
}
bool lower_hex(std::string_view value, std::size_t size) {
  return value.size() == size && std::all_of(value.begin(), value.end(), [](char item) {
    return (item >= '0' && item <= '9') || (item >= 'a' && item <= 'f');
  });
}
bool identifier(std::string_view value) {
  return !value.empty() && value.size() <= 64U &&
         std::all_of(value.begin(), value.end(), [](char item) {
           return (item >= 'a' && item <= 'z') || (item >= '0' && item <= '9') ||
                  item == '_' || item == '-';
         });
}

class Clock final : public SessionClock {
 public:
  [[nodiscard]] std::int64_t now_ns() const noexcept override { return value_; }
  void set(std::int64_t value) {
    if (value <= 0 || value < value_) refuse("fixture_time_not_monotonic");
    value_ = value;
  }
 private:
  std::int64_t value_{1};
};

class Resolver final : public SessionRoutingResolver {
 public:
  Resolver(std::vector<RoutingRecord> routes, std::string digest, std::string trading_date,
           std::int64_t timestamp_ns)
      : digest_(std::move(digest)), trading_date_(std::move(trading_date)),
        timestamp_ns_(timestamp_ns) {
    for (auto& route : routes) {
      if (!by_canonical_.emplace(route.canonical_instrument_id, std::move(route)).second)
        refuse("fixture_duplicate_route");
    }
  }
  [[nodiscard]] ResolutionResult resolve(std::string_view canonical) const override {
    const auto found = by_canonical_.find(std::string(canonical));
    return found == by_canonical_.end()
        ? ResolutionResult{std::nullopt, RoutingErrorCode::NotFound}
        : ResolutionResult{found->second, std::nullopt};
  }
  [[nodiscard]] std::string_view snapshot_digest() const noexcept override { return digest_; }
  [[nodiscard]] bool valid_for_trading_date(std::string_view value) const noexcept override {
    return value == trading_date_;
  }
  [[nodiscard]] std::optional<std::int64_t> mapping_timestamp_ns() const noexcept override {
    return timestamp_ns_;
  }
 private:
  std::map<std::string, RoutingRecord, std::less<>> by_canonical_;
  std::string digest_;
  std::string trading_date_;
  std::int64_t timestamp_ns_{};
};

RoutingRecord parse_route(const JsonValue& value) {
  const auto& object = json_object(value, "route");
  exact(object, {"canonical_instrument_id", "exchange_segment", "instrument_token",
                 "lot_size", "tick_size_paise", "trading_symbol"});
  RoutingRecord result{string_field(object, "canonical_instrument_id"),
                       string_field(object, "instrument_token", 64U),
                       string_field(object, "exchange_segment", 32U),
                       string_field(object, "trading_symbol", 128U),
                       uint_field(object, "lot_size"), uint_field(object, "tick_size_paise")};
  if (!is_canonical_instrument_id(result.canonical_instrument_id) ||
      result.exchange_segment != "nse_fo" || result.lot_size == 0U ||
      result.tick_size_paise == 0U)
    refuse("fixture_invalid_route");
  return result;
}

std::string side_name(OrderSide side) { return side == OrderSide::Buy ? "BUY" : "SELL"; }
std::string mutation_name(BrokerMutationStatus status) {
  switch (status) {
    case BrokerMutationStatus::Acknowledged: return "acknowledged";
    case BrokerMutationStatus::Rejected: return "rejected";
    case BrokerMutationStatus::Ambiguous: return "ambiguous";
  }
  refuse("broker_status_invalid");
}
std::string health_name(BrokerSessionHealth health) {
  switch (health) {
    case BrokerSessionHealth::Ready: return "ready";
    case BrokerSessionHealth::Degraded: return "degraded";
    case BrokerSessionHealth::Lost: return "lost";
    case BrokerSessionHealth::Unknown: return "unknown";
  }
  refuse("broker_health_invalid");
}
std::string model_name(PaperFillModel model) {
  return model == PaperFillModel::D51ProxyV1 ? "d51_proxy_v1" : "scripted_v1";
}

JsonValue order_json(const BrokerOrderSnapshot& order) {
  return JsonValue(JsonObject{{"canonical_instrument_id", text(order.canonical_instrument_id)},
      {"cumulative_filled_quantity", number(order.cumulative_filled_quantity)},
      {"instrument_token", text(order.instrument_token)},
      {"internal_order_id", text(order.internal_order_id)},
      {"limit_price_paise", number(order.limit_price_paise)},
      {"provenance", text(order.provenance)}, {"quantity", number(order.quantity)},
      {"side", text(side_name(order.side))}, {"state", text(order.state)}});
}
JsonValue fill_json(const BrokerFillSnapshot& fill) {
  return JsonValue(JsonObject{{"canonical_instrument_id", text(fill.canonical_instrument_id)},
      {"cumulative_filled_quantity", number(fill.cumulative_filled_quantity)},
      {"evidence_timestamp_ns", number(fill.evidence_timestamp_ns)},
      {"fill_id", text(fill.fill_id)}, {"fill_price_paise", number(fill.fill_price_paise)},
      {"instrument_token", text(fill.instrument_token)},
      {"internal_order_id", text(fill.internal_order_id)},
      {"last_fill_quantity", number(fill.last_fill_quantity)},
      {"provenance", text(fill.provenance)}});
}
JsonValue position_json(const BrokerPositionSnapshot& position) {
  return JsonValue(JsonObject{{"canonical_instrument_id", text(position.canonical_instrument_id)},
      {"instrument_token", text(position.instrument_token)},
      {"provenance", text(position.provenance)}, {"quantity", number(position.quantity)}});
}

struct SecureInput {
  std::string bytes;
  std::string digest;
};

bool safe_ancestor(const struct stat& metadata) {
  if (!S_ISDIR(metadata.st_mode) ||
      (metadata.st_uid != 0U && metadata.st_uid != ::geteuid())) return false;
  const auto permissions = metadata.st_mode & 07777U;
  return (permissions & 0022U) == 0U ||
         (metadata.st_uid == 0U && (permissions & S_ISVTX) != 0U);
}

SecureInput read_secure(const std::filesystem::path& path) {
  if (!path.is_absolute() || path.lexically_normal() != path) refuse("fixture_path_invalid");
  int parent = ::open("/", O_RDONLY | O_CLOEXEC | O_DIRECTORY);
  if (parent < 0) refuse("fixture_ancestor_unsafe");
  struct ParentGuard { int value; ~ParentGuard() { if (value >= 0) (void)::close(value); } }
      parent_guard{parent};
  struct stat directory{};
  if (::fstat(parent, &directory) != 0 || !safe_ancestor(directory))
    refuse("fixture_ancestor_unsafe");
  for (const auto& component : path.relative_path().parent_path()) {
    const auto name = component.string();
    const int next = name.empty() || name == "." || name == ".." ? -1 :
        ::openat(parent, name.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
    if (next < 0 || ::fstat(next, &directory) != 0 || !safe_ancestor(directory)) {
      if (next >= 0) (void)::close(next);
      refuse("fixture_ancestor_unsafe");
    }
    (void)::close(parent); parent = next; parent_guard.value = parent;
  }
  const auto leaf = path.filename().string();
  const int descriptor = ::openat(parent, leaf.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (descriptor < 0) refuse("fixture_unreadable");
  struct FileGuard { int value; ~FileGuard() { if (value >= 0) (void)::close(value); } }
      file_guard{descriptor};
  struct stat before{}, after{}, linked{};
  if (::fstat(descriptor, &before) != 0 || !S_ISREG(before.st_mode) ||
      before.st_uid != ::geteuid() || (before.st_mode & 0022U) != 0U || before.st_size <= 0 ||
      static_cast<std::uint64_t>(before.st_size) > kMaximumFixtureBytes)
    refuse("fixture_unsafe");
  std::string bytes(static_cast<std::size_t>(before.st_size), '\0');
  std::size_t offset = 0U;
  while (offset < bytes.size()) {
    const auto count = ::read(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) refuse("fixture_changed");
    offset += static_cast<std::size_t>(count);
  }
  if (::fstat(descriptor, &after) != 0 ||
      ::fstatat(parent, leaf.c_str(), &linked, AT_SYMLINK_NOFOLLOW) != 0 ||
      before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
      before.st_size != after.st_size || before.st_dev != linked.st_dev ||
      before.st_ino != linked.st_ino)
    refuse("fixture_replaced");
  const auto digest = sha256_hex(bytes);
  return {std::move(bytes), digest};
}

void verify_fixture_manifest(const std::filesystem::path& fixture_path,
                             std::string_view fixture_digest) {
  const auto manifest = read_secure(fixture_path.parent_path() / "MANIFEST.sha256");
  if (manifest.bytes.empty() || manifest.bytes.back() != '\n' ||
      manifest.bytes.find('\r') != std::string::npos)
    refuse("fixture_manifest_invalid");
  std::string prior_name;
  bool matched = false;
  std::size_t start = 0U;
  while (start < manifest.bytes.size()) {
    const auto end = manifest.bytes.find('\n', start);
    if (end == std::string::npos || end == start) refuse("fixture_manifest_invalid");
    const auto line = std::string_view(manifest.bytes).substr(start, end - start);
    if (line.size() < 68U || line[64] != ' ' || line[65] != ' ' ||
        !lower_hex(line.substr(0U, 64U), 64U))
      refuse("fixture_manifest_invalid");
    const auto name = std::string(line.substr(66U));
    if (name.empty() || name.size() > 128U || name.ends_with(".json") == false ||
        !std::all_of(name.begin(), name.end(), [](char item) {
          return (item >= 'a' && item <= 'z') || (item >= '0' && item <= '9') ||
                 item == '_' || item == '-' || item == '.';
        }) || (!prior_name.empty() && name <= prior_name))
      refuse("fixture_manifest_invalid");
    prior_name = name;
    if (name == fixture_path.filename().string()) {
      if (matched || !constant_time_equal(line.substr(0U, 64U), fixture_digest))
        refuse("fixture_manifest_digest_mismatch");
      matched = true;
    }
    start = end + 1U;
  }
  if (!matched) refuse("fixture_manifest_entry_missing");
}

int open_secure_output_parent(const std::filesystem::path& path) {
  if (!path.is_absolute() || path.lexically_normal() != path || path.filename().empty())
    refuse("output_path_invalid");
  int directory = ::open("/", O_RDONLY | O_CLOEXEC | O_DIRECTORY);
  if (directory < 0) refuse("output_parent_unsafe");
  struct stat metadata{};
  if (::fstat(directory, &metadata) != 0 || !safe_ancestor(metadata)) {
    (void)::close(directory);
    refuse("output_parent_unsafe");
  }
  for (const auto& component : path.relative_path().parent_path()) {
    const auto name = component.string();
    const int next = name.empty() || name == "." || name == ".." ? -1 :
        ::openat(directory, name.c_str(),
                 O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
    if (next < 0 || ::fstat(next, &metadata) != 0 || !safe_ancestor(metadata)) {
      if (next >= 0) (void)::close(next);
      (void)::close(directory);
      refuse("output_parent_unsafe");
    }
    (void)::close(directory);
    directory = next;
  }
  if (metadata.st_uid != ::geteuid() || (metadata.st_mode & 0022U) != 0U) {
    (void)::close(directory);
    refuse("output_parent_unsafe");
  }
  struct stat existing{};
  if (::fstatat(directory, path.filename().c_str(), &existing, AT_SYMLINK_NOFOLLOW) == 0) {
    (void)::close(directory);
    refuse("output_exists");
  }
  if (errno != ENOENT) {
    (void)::close(directory);
    refuse("output_parent_unsafe");
  }
  return directory;
}

void write_secure_at(int directory, const std::string& leaf, std::string_view bytes) {
  const auto temporary =
      ".shaurya-parity-result-" + std::to_string(static_cast<std::uint64_t>(::getpid()));
  const int descriptor = ::openat(directory, temporary.c_str(),
      O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
  if (descriptor < 0) refuse(errno == EEXIST ? "output_exists" : "output_create_failed");
  struct stat opened{};
  if (::fstat(descriptor, &opened) != 0 || !S_ISREG(opened.st_mode) ||
      opened.st_uid != ::geteuid() || (opened.st_mode & 07777U) != 0600U) {
    (void)::close(descriptor);
    (void)::unlinkat(directory, temporary.c_str(), 0);
    refuse("output_create_failed");
  }
  struct FileGuard {
    int directory;
    int descriptor;
    std::string temporary;
    std::string final_name;
    dev_t device;
    ino_t inode;
    bool final_linked{};
    bool committed{};
    ~FileGuard() {
      if (!committed && final_linked) {
        struct stat linked{};
        if (::fstatat(directory, final_name.c_str(), &linked, AT_SYMLINK_NOFOLLOW) == 0 &&
            linked.st_dev == device && linked.st_ino == inode)
          (void)::unlinkat(directory, final_name.c_str(), 0);
      }
      (void)::unlinkat(directory, temporary.c_str(), 0);
      if (descriptor >= 0) (void)::close(descriptor);
    }
  } file_guard{directory, descriptor, temporary, leaf, opened.st_dev, opened.st_ino};
  std::size_t offset = 0U;
  while (offset < bytes.size()) {
    const auto count = ::write(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) refuse("output_write_failed");
    offset += static_cast<std::size_t>(count);
  }
  if (::fsync(descriptor) != 0) refuse("output_sync_failed");
  if (::linkat(directory, temporary.c_str(), directory, leaf.c_str(), 0) != 0)
    refuse(errno == EEXIST ? "output_exists" : "output_publish_failed");
  file_guard.final_linked = true;
  struct stat linked{};
  if (
      ::fstatat(directory, leaf.c_str(), &linked, AT_SYMLINK_NOFOLLOW) != 0 ||
      !S_ISREG(opened.st_mode) || opened.st_dev != linked.st_dev || opened.st_ino != linked.st_ino)
    refuse("output_replaced");
  if (::unlinkat(directory, temporary.c_str(), 0) != 0 || ::fsync(directory) != 0)
    refuse("output_sync_failed");
  file_guard.committed = true;
}

JsonValue harness_version() {
  if (!lower_hex(kSourceRevision, 40U) ||
      !lower_hex(SHAURYA_PARITY_SCHEMA_DIGEST, 64U) ||
      !lower_hex(SHAURYA_PARITY_CLIENT_CONTRACT_DIGEST, 64U))
    refuse("harness_build_unattested");
  JsonArray models{text("d51_proxy_v1"), text("scripted_v1")};
  return JsonValue(JsonObject{{"build_sha256", text(running_executable_digest())},
      {"client_contract_sha256", text(SHAURYA_PARITY_CLIENT_CONTRACT_DIGEST)},
      {"contract_schema_sha256", text(SHAURYA_PARITY_SCHEMA_DIGEST)},
      {"executable", text("shaurya-parity-harness")},
      {"model_versions", JsonValue(std::move(models))},
      {"protocol_version", text("1.0.0")}, {"schema_version", text("1.0.0")},
      {"source_commit", text(kSourceRevision)}});
}

JsonValue run_scenario(const SecureInput& fixture, int output_directory) {
  const auto document = parse_json(fixture.bytes, kMaximumFixtureBytes);
  const auto canonical_fixture = canonical_json(document);
  if (canonical_fixture + "\n" != fixture.bytes) refuse("fixture_noncanonical");
  const auto& root = json_object(document, "parity_fixture");
  exact(root, {"execution_session_id", "mapping_timestamp_ns", "mode", "model",
               "risk_configuration", "routes", "routing_snapshot_digest", "scenario_id",
               "schema_version", "steps", "strategy_id", "strategy_run_id", "trading_date"});
  if (string_field(root, "schema_version", 16U) != "1.0.0")
    refuse("fixture_version_invalid");
  if (string_field(root, "mode", 16U) != "shadow") refuse("live_mode_refused");
  const auto scenario_id = string_field(root, "scenario_id", 64U);
  if (!identifier(scenario_id)) refuse("fixture_scenario_id_invalid");
  const auto session_id = string_field(root, "execution_session_id", 64U);
  const auto strategy_id = string_field(root, "strategy_id", 64U);
  const auto strategy_run_id = string_field(root, "strategy_run_id", 64U);
  if (!is_canonical_uuid(session_id) || !is_canonical_uuid(strategy_run_id) ||
      !identifier(strategy_id)) refuse("fixture_correlation_invalid");
  const auto trading_date = string_field(root, "trading_date", 10U);
  const auto routing_digest = string_field(root, "routing_snapshot_digest", 64U);
  if (!lower_hex(routing_digest, 64U)) refuse("fixture_routing_digest_invalid");
  const auto mapping_timestamp = int_field(root, "mapping_timestamp_ns");
  if (mapping_timestamp <= 0) refuse("fixture_mapping_timestamp_invalid");
  const auto model_text = string_field(root, "model", 32U);
  PaperFillModel model;
  if (model_text == "d51_proxy_v1") model = PaperFillModel::D51ProxyV1;
  else if (model_text == "scripted_v1") model = PaperFillModel::ScriptedV1;
  else refuse(model_text == "live" ? "live_mode_refused" : "fixture_model_invalid");
  const auto& route_values = json_array(required(root, "routes"), "routes");
  if (route_values.empty() || route_values.size() > 128U) refuse("fixture_routes_invalid");
  std::vector<RoutingRecord> routes;
  routes.reserve(route_values.size());
  for (const auto& value : route_values) routes.push_back(parse_route(value));
  auto risk = RiskConfiguration::parse(canonical_json(required(root, "risk_configuration")));
  if (risk.trading_date != trading_date) refuse("fixture_risk_date_mismatch");
  Resolver resolver(std::move(routes), routing_digest, trading_date, mapping_timestamp);
  Clock clock;

  const auto work_name =
      ".shaurya-parity-" + std::to_string(static_cast<std::uint64_t>(::getpid()));
  if (::mkdirat(output_directory, work_name.c_str(), 0700) != 0)
    refuse("harness_work_directory_failed");
  const int work_descriptor = ::openat(output_directory, work_name.c_str(),
                                       O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
  struct stat work_metadata{};
  if (work_descriptor < 0 || ::fstat(work_descriptor, &work_metadata) != 0 ||
      !S_ISDIR(work_metadata.st_mode) || work_metadata.st_uid != ::geteuid() ||
      (work_metadata.st_mode & 07777U) != 0700U) {
    if (work_descriptor >= 0) (void)::close(work_descriptor);
    (void)::unlinkat(output_directory, work_name.c_str(), AT_REMOVEDIR);
    refuse("harness_work_directory_failed");
  }
  struct WorkGuard {
    int parent;
    int directory;
    std::string name;
    ~WorkGuard() {
      if (directory >= 0) {
        (void)::unlinkat(directory, "events.ledger", 0);
        (void)::close(directory);
      }
      (void)::unlinkat(parent, name.c_str(), AT_REMOVEDIR);
    }
  } work_guard{output_directory, work_descriptor, work_name};
  auto audit = std::make_unique<ExecutionLedgerSessionAdapter>(
      ExecutionLedgerSessionAdapter::create_new_at(work_descriptor, "events.ledger"));
  auto broker = std::make_unique<PaperBroker>(model, model == PaperFillModel::ScriptedV1);
  auto session = std::make_unique<ExecutionSession>(
      session_id, RiskEngine(risk), ReplayedBrokerState{}, *audit, resolver, *broker, clock);
  if (!session->preflight()) refuse("harness_preflight_failed");

  JsonArray intents, actions, inventories;
  std::map<std::string, OrderIntent, std::less<>> intents_by_id;
  std::map<std::string, std::string, std::less<>> order_by_intent;
  std::uint64_t observation_sequence = 0U;
  std::uint64_t broker_update_sequence = 0U;
  const auto capture_inventory = [&](std::size_t step_index, std::size_t substep_index,
                                     std::string boundary) {
    JsonArray positions;
    for (const auto& position : broker->query_positions().items)
      positions.push_back(position_json(position));
    inventories.emplace_back(JsonValue(JsonObject{
        {"boundary", text(std::move(boundary))}, {"positions", JsonValue(std::move(positions))},
        {"step_index", number(static_cast<std::uint64_t>(step_index))},
        {"substep_index", number(static_cast<std::uint64_t>(substep_index))},
        {"timestamp_ns", number(clock.now_ns())}}));
  };
  const auto& steps = json_array(required(root, "steps"), "steps");
  if (steps.empty() || steps.size() > 4096U) refuse("fixture_steps_invalid");
  for (std::size_t step_index = 0U; step_index < steps.size(); ++step_index) {
    const auto& step = json_object(steps[step_index], "step");
    const auto kind = string_field(step, "kind", 32U);
    if (kind == "observation") {
      exact(step, {"book", "kind"});
      const auto book_bytes = canonical_json(required(step, "book"));
      const auto book = StrategyBookObservation::parse(book_bytes);
      clock.set(book.receive_timestamp_ns);
      const auto observation = book.derive_market_observation();
      if (!session->record_market_observation_accepted(
              ++observation_sequence, sha256_hex(book_bytes), observation))
        refuse("harness_market_evidence_failed");
      session->accept_observation(observation);
    } else if (kind == "intent") {
      exact(step, {"intent", "kind"});
      const auto intent_bytes = canonical_json(required(step, "intent"));
      const auto intent = OrderIntent::parse(intent_bytes);
      if (intent.execution_session_id != session_id || intent.strategy_id != strategy_id ||
          intent.strategy_run_id != strategy_run_id)
        refuse("fixture_intent_scope_invalid");
      clock.set(std::max(clock.now_ns(), intent.created_at_ns));
      const auto result = session->accept_intent(intent);
      intents.push_back(parse_json(intent.to_json()));
      JsonObject action{{"action", text(intent.action == IntentAction::Place ? "place" :
          intent.action == IntentAction::Modify ? "modify" : "cancel")},
          {"decision", text(result.decision.decision)}, {"intent_id", text(intent.intent_id)},
          {"semantic_fingerprint", text(intent.semantic_fingerprint())},
          {"step_index", number(static_cast<std::uint64_t>(step_index))}};
      if (result.broker_result) {
        action.emplace("broker_status", text(mutation_name(result.broker_result->status)));
        action.emplace("internal_order_id", text(result.broker_result->internal_order_id));
        const auto verified = audit->ledger().verify(LedgerVerificationMode::RetainRecords);
        bool attempt_correlated = false;
        bool outcome_correlated = false;
        if (!verified.clean()) refuse("intent_ledger_correlation_invalid");
        for (const auto& record : verified.records) {
          if (!record.event.intent_id || *record.event.intent_id != intent.intent_id) continue;
          if (record.event.internal_order_id &&
              *record.event.internal_order_id != result.broker_result->internal_order_id)
            refuse("intent_ledger_correlation_invalid");
          attempt_correlated |= record.event.event_type == "submission_started" ||
                                record.event.event_type == "modify_requested" ||
                                record.event.event_type == "cancel_requested";
          outcome_correlated |= record.event.event_type == "broker_acknowledged" ||
                                record.event.event_type == "broker_rejected" ||
                                record.event.event_type == "modified" ||
                                record.event.event_type == "modify_rejected" ||
                                record.event.event_type == "cancelled" ||
                                record.event.event_type == "cancel_rejected" ||
                                record.event.event_type == "ambiguous_submission";
        }
        if (!attempt_correlated || !outcome_correlated)
          refuse("intent_ledger_correlation_invalid");
        if (intent.action == IntentAction::Place &&
            result.broker_result->status == BrokerMutationStatus::Acknowledged) {
          const auto broker_orders = broker->query_orders();
          const auto exact_order = std::find_if(
              broker_orders.items.begin(), broker_orders.items.end(), [&](const auto& order) {
                return order.internal_order_id == result.broker_result->internal_order_id;
              });
          if (exact_order == broker_orders.items.end())
            refuse("intent_broker_correlation_invalid");
          order_by_intent.insert_or_assign(intent.intent_id,
                                           result.broker_result->internal_order_id);
        }
      }
      actions.emplace_back(JsonValue(std::move(action)));
      intents_by_id.insert_or_assign(intent.intent_id, intent);
    } else if (kind == "scripted_updates") {
      exact(step, {"kind", "updates"});
      if (model != PaperFillModel::ScriptedV1) refuse("scripted_update_model_invalid");
      const auto& updates = json_array(required(step, "updates"), "updates");
      if (updates.empty() || updates.size() > 1024U) refuse("scripted_updates_invalid");
      for (std::size_t update_index = 0U; update_index < updates.size(); ++update_index) {
        const auto& value = updates[update_index];
        const auto& item = json_object(value, "scripted_update");
        exact(item, {"cumulative_filled_quantity", "intent_id", "kind", "timestamp_ns",
                     "update_id"});
        const auto intent_id = string_field(item, "intent_id", 64U);
        const auto owner = intents_by_id.find(intent_id);
        const auto order = order_by_intent.find(intent_id);
        if (owner == intents_by_id.end() || order == order_by_intent.end())
          refuse("scripted_update_unknown_intent");
        const auto update_kind = string_field(item, "kind", 32U);
        ScriptedPaperEventKind parsed_kind;
        if (update_kind == "partial_fill") parsed_kind = ScriptedPaperEventKind::PartialFill;
        else if (update_kind == "fill") parsed_kind = ScriptedPaperEventKind::Fill;
        else if (update_kind == "reject") parsed_kind = ScriptedPaperEventKind::Reject;
        else if (update_kind == "session_loss") parsed_kind = ScriptedPaperEventKind::SessionLoss;
        else if (update_kind == "ambiguous") parsed_kind = ScriptedPaperEventKind::Ambiguous;
        else refuse("scripted_update_kind_invalid");
        const auto update_id = string_field(item, "update_id", 64U);
        if (!identifier(update_id)) refuse("scripted_update_id_invalid");
        ScriptedPaperEvent event{parsed_kind, update_id,
            order->second, uint_field(item, "cumulative_filled_quantity"),
            int_field(item, "timestamp_ns")};
        clock.set(event.timestamp_ns);
        const auto generated = broker->apply_scripted({event});
        for (const auto& fill : generated) {
          if (fill.internal_order_id != order->second) refuse("scripted_fill_correlation_lost");
          BrokerUpdateEnvelope update;
          update.sequence = ++broker_update_sequence;
          update.update_id = fill.fill_id; update.strategy_id = owner->second.strategy_id;
          update.strategy_run_id = owner->second.strategy_run_id;
          update.intent_id = owner->second.intent_id;
          update.internal_order_id = fill.internal_order_id;
          update.kind = OrderEventKind::FillUpdate;
          update.cumulative_filled_quantity = fill.cumulative_filled_quantity;
          update.fill_price_paise = fill.fill_price_paise;
          update.provenance = fill.provenance;
          update.evidence_timestamp_ns = fill.evidence_timestamp_ns;
          if (!session->accept_broker_update(update)) refuse("scripted_fill_apply_failed");
        }
        if (event.kind != ScriptedPaperEventKind::PartialFill &&
            event.kind != ScriptedPaperEventKind::Fill) {
          BrokerUpdateEnvelope update;
          update.sequence = ++broker_update_sequence;
          update.update_id = event.update_id; update.strategy_id = owner->second.strategy_id;
          update.strategy_run_id = owner->second.strategy_run_id;
          update.intent_id = owner->second.intent_id;
          update.internal_order_id = event.internal_order_id;
          update.provenance = "simulated_proxy";
          if (event.kind == ScriptedPaperEventKind::SessionLoss) update.session_lost = true;
          else if (event.kind == ScriptedPaperEventKind::Reject) {
            update.kind = OrderEventKind::BrokerRejected; update.error_code = "paper_rejected";
          } else {
            update.kind = OrderEventKind::SubmissionAmbiguous;
            update.error_code = "broker_outcome_uncertain";
          }
          const bool accepted = session->accept_broker_update(update);
          if (!accepted && !(session->safety_stopped() &&
                             (event.kind == ScriptedPaperEventKind::SessionLoss ||
                              event.kind == ScriptedPaperEventKind::Ambiguous ||
                              event.kind == ScriptedPaperEventKind::Reject)))
            refuse("scripted_update_apply_failed");
        }
        capture_inventory(step_index, update_index, "scripted_update");
      }
    } else if (kind == "safety_stop") {
      exact(step, {"kind", "reason"});
      const auto reason = string_field(step, "reason", 128U);
      if (!identifier(reason)) refuse("safety_stop_reason_invalid");
      session->activate_kill_switch(reason);
    } else if (kind == "ipc_loss") {
      exact(step, {"kind", "peer_role"});
      const auto role = string_field(step, "peer_role", 32U);
      PeerRole peer_role;
      if (role == "market_publisher") peer_role = PeerRole::MarketPublisher;
      else if (role == "strategy_client") peer_role = PeerRole::StrategyClient;
      else refuse("ipc_loss_role_invalid");
      ExecutorConfiguration configuration;
      configuration.execution_session_id = session_id;
      configuration.expected_strategy_id = strategy_id;
      configuration.queue_capacities.fill(32U);
      {
        Executor executor(std::move(configuration), *session, audit->ledger(), clock);
        executor.record_peer_disconnect(peer_role);
      }
    } else if (kind == "market_session_cutoff") {
      exact(step, {"kind", "timestamp_ns"});
      clock.set(int_field(step, "timestamp_ns"));
      session->activate_kill_switch("market_session_cutoff");
    } else if (kind == "restart") {
      exact(step, {"kind"});
      const auto verified = audit->ledger().verify(LedgerVerificationMode::RetainRecords);
      if (!verified.clean()) refuse("harness_restart_ledger_invalid");
      const auto recovered = recover_paper_broker(verified, model);
      broker_update_sequence = std::max(
          broker_update_sequence, recovered.replayed.reconstructed.last_broker_update_sequence);
      session.reset(); broker.reset(); audit.reset();
      audit = std::make_unique<ExecutionLedgerSessionAdapter>(
          ExecutionLedgerSessionAdapter::open_existing_at(work_descriptor, "events.ledger"));
      broker = std::make_unique<PaperBroker>(recovered.snapshot,
                                             model == PaperFillModel::ScriptedV1);
      session = std::make_unique<ExecutionSession>(session_id, RiskEngine(risk),
          recovered.replayed, *audit, resolver, *broker, clock);
      if (!session->preflight()) refuse("harness_restart_reconciliation_failed");
    } else {
      refuse("fixture_step_kind_invalid");
    }
    if (kind != "scripted_updates") capture_inventory(step_index, 0U, "step");
  }

  const auto verified = audit->ledger().verify(LedgerVerificationMode::RetainRecords);
  if (!verified.clean()) refuse("harness_final_ledger_invalid");
  JsonArray events, incidents;
  for (const auto& record : verified.records) {
    events.push_back(parse_json(record.event.to_json()));
    const auto incident = record.event.event_type == "safety_stop" ||
                          record.event.event_type == "reconciliation_required" ||
                          record.event.event_type == "ambiguous_submission" ||
                          record.event.event_type == "risk_rejected" ||
                          record.event.event_type == "broker_rejected" ||
                          record.event.event_type == "modify_rejected" ||
                          record.event.event_type == "cancel_rejected";
    if (incident) {
      std::string code = record.event.event_type;
      for (const auto key : {"reason", "error_code", "rejection_code"}) {
        const auto found = record.event.payload.find(key);
        if (found != record.event.payload.end()) { code = json_string(found->second, key); break; }
      }
      const bool critical = record.event.event_type == "safety_stop" ||
                            record.event.event_type == "reconciliation_required" ||
                            record.event.event_type == "ambiguous_submission";
      incidents.emplace_back(JsonObject{
          {"code", text(std::move(code))}, {"event_sequence", number(record.sequence)},
          {"incident_type", text(record.event.event_type)},
          {"severity", text(critical ? "critical" : "warning")},
          {"timestamp_ns", number(record.event.timestamp_ns)}});
    }
  }
  JsonArray orders, fills, positions;
  for (const auto& order : broker->query_orders().items) orders.push_back(order_json(order));
  for (const auto& fill : broker->query_trades().items) fills.push_back(fill_json(fill));
  for (const auto& position : broker->query_positions().items)
    positions.push_back(position_json(position));
  const auto pnl = broker->query_pnl();
  const bool pnl_authoritative = pnl.status == BrokerQueryStatus::Authoritative;
  JsonObject final_state{{"broker_health", text(health_name(broker->session_health()))},
      {"daily_loss_paise", pnl_authoritative ? number(pnl.daily_loss_paise) : JsonValue()},
      {"drawdown_paise", pnl_authoritative ? number(pnl.drawdown_paise) : JsonValue()},
      {"fills", number(static_cast<std::uint64_t>(fills.size()))},
      {"orders", JsonValue(std::move(orders))}, {"positions", JsonValue(std::move(positions))},
      {"pnl_authoritative", JsonValue(pnl_authoritative)},
      {"safety_stopped", JsonValue(session->safety_stopped())},
      {"session_ready", JsonValue(session->ready())}};
  return JsonValue(JsonObject{{"actions", JsonValue(std::move(actions))},
      {"build_sha256", text(running_executable_digest())},
      {"client_contract_sha256", text(SHAURYA_PARITY_CLIENT_CONTRACT_DIGEST)},
      {"contract_schema_sha256", text(SHAURYA_PARITY_SCHEMA_DIGEST)},
      {"events", JsonValue(std::move(events))}, {"final_state", JsonValue(std::move(final_state))},
      {"fixture_sha256", text(fixture.digest)}, {"incidents", JsonValue(std::move(incidents))},
      {"intents", JsonValue(std::move(intents))},
      {"inventory", JsonValue(std::move(inventories))},
      {"model_version", text(model_name(model))}, {"protocol_version", text("1.0.0")},
      {"scenario_id", text(scenario_id)}, {"schema_version", text("1.0.0")},
      {"source_commit", text(kSourceRevision)}, {"fills", JsonValue(std::move(fills))}});
}

}  // namespace

int parity_harness_cli(const std::vector<std::string>& arguments,
                       std::ostream& output, std::ostream& error) {
  try {
    if (arguments.size() == 1U && arguments[0] == "version") {
      output << canonical_json(harness_version()) << '\n';
      return 0;
    }
    if (arguments.size() != 5U || arguments[0] != "run" || arguments[1] != "--fixture" ||
        arguments[3] != "--output")
      refuse("harness_usage_invalid");
    const std::filesystem::path fixture_path(arguments[2]);
    const std::filesystem::path output_path(arguments[4]);
    const int output_directory = open_secure_output_parent(output_path);
    struct OutputDirectoryGuard {
      int value;
      ~OutputDirectoryGuard() { if (value >= 0) (void)::close(value); }
    } output_directory_guard{output_directory};
    const auto fixture = read_secure(fixture_path);
    verify_fixture_manifest(fixture_path, fixture.digest);
    auto result = canonical_json(run_scenario(fixture, output_directory));
    result.push_back('\n');
    write_secure_at(output_directory, output_path.filename().string(), result);
    output << "[SHAURYA_PARITY_OK] fixture_sha256=" << fixture.digest << '\n';
    return 0;
  } catch (const std::exception& exception) {
    error << "[SHAURYA_PARITY_REFUSED] code=" << exception.what() << '\n';
    return 2;
  }
}

}  // namespace shaurya::execution
