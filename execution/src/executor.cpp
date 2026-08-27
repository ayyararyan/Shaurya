#include "shaurya/execution/executor.hpp"

#include "shaurya/execution/build_attestation.hpp"
#include "shaurya/execution/canonical_json.hpp"
#include "shaurya/execution/ledger_replay.hpp"
#include "shaurya/execution/paper_broker.hpp"

#include <algorithm>
#include <charconv>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <fcntl.h>
#include <fstream>
#include <future>
#include <iostream>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <poll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>
#include <utility>

#if defined(__linux__)
#include <sys/random.h>
#elif defined(__APPLE__)
#include <mach-o/dyld.h>
#endif

namespace shaurya::execution {
namespace {
[[noreturn]] void fail(std::string code) { throw IpcProtocolError(std::move(code)); }
const JsonValue& required(const JsonObject& object, std::string_view key) {
  const auto iterator = object.find(key); if (iterator == object.end()) fail("config_missing_field");
  return iterator->second;
}
void exact(const JsonObject& object, std::initializer_list<std::string_view> fields) {
  if (object.size() != fields.size()) fail("config_unknown_or_missing_field");
  for (const auto field : fields) if (!object.contains(field)) fail("config_missing_field");
}
std::string text(const JsonObject& object, std::string_view key, std::size_t maximum = 256U) {
  try {
    const auto& value = json_string(required(object, key), key);
    if (value.empty() || value.size() > maximum) fail("config_invalid_string");
    for (const char raw : value) {
      const auto item = static_cast<unsigned char>(raw);
      if (item < 0x20U || item > 0x7eU) fail("config_invalid_string");
    }
    return value;
  } catch (const JsonError&) { fail("config_invalid_field"); }
}
std::uint64_t number(const JsonObject& object, std::string_view key) {
  try { return json_uint64(required(object, key), key); }
  catch (const JsonError&) { fail("config_invalid_field"); }
}
std::int64_t signed_number(const JsonObject& object, std::string_view key) {
  try { return json_int64(required(object, key), key); }
  catch (const JsonError&) { fail("config_invalid_field"); }
}
bool digest(std::string_view value) {
  return value.size() == 64U && std::all_of(value.begin(), value.end(), [](char item) {
    return (item >= '0' && item <= '9') || (item >= 'a' && item <= 'f');
  });
}
bool lowercase_hex(std::string_view value, std::size_t width) {
  return value.size() == width && std::all_of(value.begin(), value.end(), [](char item) {
    return (item >= '0' && item <= '9') || (item >= 'a' && item <= 'f');
  });
}
std::filesystem::path protected_path(const JsonObject& object, std::string_view key) {
  std::filesystem::path path(text(object, key, 1024U));
  if (!path.is_absolute() || path.lexically_normal() != path) fail("config_path_invalid");
  return path;
}
bool beneath(const std::filesystem::path& path, const std::filesystem::path& root) {
  const auto relative = path.lexically_relative(root);
  if (relative.empty() || relative.is_absolute()) return false;
  return *relative.begin() != "..";
}
bool socket_basename(std::string_view value) {
  if (value.empty() || value.size() > 80U || value == "." || value == "..") return false;
  return std::all_of(value.begin(), value.end(), [](char item) {
    return (item >= 'A' && item <= 'Z') || (item >= 'a' && item <= 'z') ||
           (item >= '0' && item <= '9') || item == '.' || item == '_' || item == '-';
  });
}
bool safe_directory_descriptor(int descriptor, bool protected_leaf) {
  struct stat metadata{};
  if (::fstat(descriptor, &metadata) != 0 || !S_ISDIR(metadata.st_mode)) return false;
  const auto permissions = metadata.st_mode & 07777U;
  if (protected_leaf)
    return metadata.st_uid == ::geteuid() && permissions == 0700U;
  if (metadata.st_uid != 0U && metadata.st_uid != ::geteuid()) return false;
  const bool writable_by_others = (permissions & 0022U) != 0U;
  return !writable_by_others ||
         (metadata.st_uid == 0U && (permissions & S_ISVTX) != 0U);
}
ExpectedPeerIdentity peer_identity(const JsonObject& root, std::string_view key, PeerRole role,
                                   std::filesystem::path& configuration_path) {
  const auto& object = json_object(required(root, key), key);
  exact(object, {"configuration_digest", "configuration_path", "executable_digest", "gid",
                 "protocol_version", "uid"});
  ExpectedPeerIdentity result; result.role = role;
  result.uid = number(object, "uid"); result.gid = number(object, "gid");
  result.executable_digest = text(object, "executable_digest", 64U);
  result.configuration_digest = text(object, "configuration_digest", 64U);
  configuration_path = protected_path(object, "configuration_path");
  result.protocol_version = text(object, "protocol_version", 16U);
  if (!digest(result.executable_digest) || !digest(result.configuration_digest) ||
      result.protocol_version != "1.0.0") fail("config_peer_identity_invalid");
  return result;
}
std::string read_protected(const std::filesystem::path& path, std::size_t maximum) {
  if (!path.is_absolute() || path.lexically_normal() != path) fail("protected_path_invalid");
  int parent = ::open("/", O_RDONLY | O_CLOEXEC | O_DIRECTORY);
  if (parent < 0 || !safe_directory_descriptor(parent, false))
    fail("protected_file_unsafe");
  struct ParentGuard { int value; ~ParentGuard() { if (value >= 0) (void)::close(value); } }
      parent_guard{parent};
  for (const auto& component : path.relative_path().parent_path()) {
    const auto name = component.string();
    if (name.empty() || name == "." || name == "..") fail("protected_file_unsafe");
    const int next = ::openat(parent, name.c_str(),
                              O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
    if (next < 0 || !safe_directory_descriptor(next, false)) {
      if (next >= 0) (void)::close(next);
      fail("protected_file_unsafe");
    }
    (void)::close(parent);
    parent = next;
    parent_guard.value = parent;
  }
  if (!safe_directory_descriptor(parent, true)) fail("protected_file_unsafe");
  const auto leaf = path.filename().string();
  const int descriptor = ::openat(parent, leaf.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (descriptor < 0) fail("protected_file_unsafe");
  struct Guard { int value; ~Guard() { if (value >= 0) (void)::close(value); } } guard{descriptor};
  struct stat opened{};
  if (::fstat(descriptor, &opened) != 0 || !S_ISREG(opened.st_mode) ||
      opened.st_uid != ::geteuid() || (opened.st_mode & 077U) != 0U ||
      opened.st_size <= 0 || static_cast<std::uint64_t>(opened.st_size) > maximum)
    fail("protected_file_unsafe");
  std::string bytes(static_cast<std::size_t>(opened.st_size), '\0');
  std::size_t offset = 0;
  while (offset < bytes.size()) {
    const auto count = ::read(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) fail("protected_file_changed");
    offset += static_cast<std::size_t>(count);
  }
  struct stat after{};
  if (::fstatat(parent, leaf.c_str(), &after, AT_SYMLINK_NOFOLLOW) != 0 ||
      after.st_dev != opened.st_dev ||
      after.st_ino != opened.st_ino || after.st_size != opened.st_size ||
      after.st_uid != opened.st_uid || after.st_mode != opened.st_mode
#if defined(__APPLE__)
      || after.st_mtimespec.tv_sec != opened.st_mtimespec.tv_sec
      || after.st_mtimespec.tv_nsec != opened.st_mtimespec.tv_nsec
      || after.st_ctimespec.tv_sec != opened.st_ctimespec.tv_sec
      || after.st_ctimespec.tv_nsec != opened.st_ctimespec.tv_nsec
#else
      || after.st_mtim.tv_sec != opened.st_mtim.tv_sec
      || after.st_mtim.tv_nsec != opened.st_mtim.tv_nsec
      || after.st_ctim.tv_sec != opened.st_ctim.tv_sec
      || after.st_ctim.tv_nsec != opened.st_ctim.tv_nsec
#endif
      )
    fail("protected_file_replaced");
  return bytes;
}
std::shared_ptr<int> open_protected_directory(const std::filesystem::path& path) {
  if (!path.is_absolute() || path.lexically_normal() != path)
    fail("protected_root_invalid");
  int descriptor = ::open("/", O_RDONLY | O_CLOEXEC | O_DIRECTORY);
  if (descriptor < 0 || !safe_directory_descriptor(descriptor, false))
    fail("protected_root_unsafe");
  for (const auto& component : path.relative_path()) {
    const auto name = component.string();
    const int next = name.empty() || name == "." || name == ".." ? -1 :
        ::openat(descriptor, name.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
    (void)::close(descriptor);
    if (next < 0 || !safe_directory_descriptor(next, false)) {
      if (next >= 0) (void)::close(next);
      fail("protected_root_unsafe");
    }
    descriptor = next;
  }
  if (!safe_directory_descriptor(descriptor, true)) {
    (void)::close(descriptor);
    fail("protected_root_unsafe");
  }
  return std::shared_ptr<int>(new int(descriptor), [](int* value) {
    if (value != nullptr) {
      if (*value >= 0) (void)::close(*value);
      delete value;
    }
  });
}
bool same_inode(const struct stat& left, const struct stat& right);
std::string read_protected_beneath(const ExecutorConfiguration& configuration,
                                   const std::filesystem::path& path,
                                   std::size_t maximum,
                                   std::int64_t* timestamp_ns = nullptr) {
  if (!configuration.protected_artifact_descriptor ||
      !beneath(path, configuration.protected_artifact_root))
    fail("protected_path_outside_root");
  int parent = ::dup(*configuration.protected_artifact_descriptor);
  if (parent < 0) fail("protected_root_unavailable");
  struct ParentGuard { int value; ~ParentGuard() { if (value >= 0) (void)::close(value); } }
      parent_guard{parent};
  const auto relative = path.lexically_relative(configuration.protected_artifact_root);
  for (const auto& component : relative.parent_path()) {
    const auto name = component.string();
    const int next = name.empty() || name == "." || name == ".." ? -1 :
        ::openat(parent, name.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
    if (next < 0 || !safe_directory_descriptor(next, true)) {
      if (next >= 0) (void)::close(next);
      fail("protected_file_unsafe");
    }
    (void)::close(parent);
    parent = next;
    parent_guard.value = parent;
  }
  const auto leaf = relative.filename().string();
  const int descriptor = ::openat(parent, leaf.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (descriptor < 0) fail("protected_file_unsafe");
  struct FileGuard { int value; ~FileGuard() { if (value >= 0) (void)::close(value); } }
      file_guard{descriptor};
  struct stat before{};
  if (::fstat(descriptor, &before) != 0 || !S_ISREG(before.st_mode) ||
      before.st_uid != ::geteuid() || (before.st_mode & 077U) != 0U || before.st_size <= 0 ||
      static_cast<std::uint64_t>(before.st_size) > maximum)
    fail("protected_file_unsafe");
  std::string bytes(static_cast<std::size_t>(before.st_size), '\0');
  std::size_t offset = 0U;
  while (offset < bytes.size()) {
    const auto count = ::read(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) fail("protected_file_changed");
    offset += static_cast<std::size_t>(count);
  }
  struct stat after{}, linked{};
  if (::fstat(descriptor, &after) != 0 || !same_inode(before, after) ||
      ::fstatat(parent, leaf.c_str(), &linked, AT_SYMLINK_NOFOLLOW) != 0 ||
      !same_inode(before, linked))
    fail("protected_file_replaced");
  if (timestamp_ns != nullptr) {
#if defined(__APPLE__)
    const auto seconds = before.st_mtimespec.tv_sec;
    const auto nanoseconds = before.st_mtimespec.tv_nsec;
#else
    const auto seconds = before.st_mtim.tv_sec;
    const auto nanoseconds = before.st_mtim.tv_nsec;
#endif
    if (seconds <= 0 || seconds > std::numeric_limits<std::int64_t>::max() / 1'000'000'000LL)
      fail("protected_file_timestamp_invalid");
    *timestamp_ns = static_cast<std::int64_t>(seconds) * 1'000'000'000LL + nanoseconds;
  }
  return bytes;
}
bool same_inode(const struct stat& left, const struct stat& right) {
  return left.st_dev == right.st_dev && left.st_ino == right.st_ino &&
         left.st_mode == right.st_mode && left.st_uid == right.st_uid &&
         left.st_gid == right.st_gid && left.st_size == right.st_size
#if defined(__APPLE__)
         && left.st_mtimespec.tv_sec == right.st_mtimespec.tv_sec
         && left.st_mtimespec.tv_nsec == right.st_mtimespec.tv_nsec
         && left.st_ctimespec.tv_sec == right.st_ctimespec.tv_sec
         && left.st_ctimespec.tv_nsec == right.st_ctimespec.tv_nsec
#else
         && left.st_mtim.tv_sec == right.st_mtim.tv_sec
         && left.st_mtim.tv_nsec == right.st_mtim.tv_nsec
         && left.st_ctim.tv_sec == right.st_ctim.tv_sec
         && left.st_ctim.tv_nsec == right.st_ctim.tv_nsec
#endif
      ;
}
std::string read_launch_attestation(const ExecutorConfiguration& configuration,
                                    const std::filesystem::path& path) {
  const auto& root = configuration.launch_attestation_root;
  if (!root.is_absolute() || root.lexically_normal() != root ||
      !path.is_absolute() || path.lexically_normal() != path || path.parent_path() != root ||
      path.extension() != ".json" || !is_canonical_uuid(path.stem().string()))
    fail("launch_attestation_path_invalid");
  if (!configuration.protected_artifact_descriptor ||
      root.parent_path() != configuration.protected_artifact_root)
    fail("launch_attestation_root_unsafe");
  const auto root_basename = root.filename().string();
  if (!configuration.launch_attestation_root_descriptor)
    fail("launch_attestation_root_unsafe");
  int root_descriptor = ::dup(*configuration.launch_attestation_root_descriptor);
  if (!safe_directory_descriptor(root_descriptor, true))
    fail("launch_attestation_root_unsafe");
  struct RootGuard { int value; ~RootGuard() { if (value >= 0) (void)::close(value); } }
      root_guard{root_descriptor};
  struct stat root_opened{}, root_linked{};
  if (::fstat(root_descriptor, &root_opened) != 0 ||
      ::fstatat(*configuration.protected_artifact_descriptor, root_basename.c_str(),
                &root_linked, AT_SYMLINK_NOFOLLOW) != 0 ||
      !same_inode(root_opened, root_linked))
    fail("launch_attestation_root_replaced");
  const auto filename = path.filename().string();
  const int descriptor = ::openat(root_descriptor, filename.c_str(),
                                  O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (descriptor < 0) fail("launch_attestation_file_unsafe");
  struct FileGuard { int value; ~FileGuard() { if (value >= 0) (void)::close(value); } }
      file_guard{descriptor};
  struct stat opened{};
  if (::fstat(descriptor, &opened) != 0 || !S_ISREG(opened.st_mode) ||
      opened.st_uid != ::geteuid() || (opened.st_mode & 07777U) != 0600U ||
      opened.st_size <= 0 || opened.st_size > 32 * 1024)
    fail("launch_attestation_file_unsafe");
  std::string bytes(static_cast<std::size_t>(opened.st_size), '\0');
  std::size_t offset = 0U;
  while (offset < bytes.size()) {
    const auto count = ::read(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) fail("launch_attestation_file_changed");
    offset += static_cast<std::size_t>(count);
  }
  struct stat opened_after{}, path_after{}, root_after{};
  if (::fstat(descriptor, &opened_after) != 0 || !same_inode(opened, opened_after) ||
      ::fstatat(root_descriptor, filename.c_str(), &path_after, AT_SYMLINK_NOFOLLOW) != 0 ||
      !same_inode(opened, path_after) ||
      ::fstatat(*configuration.protected_artifact_descriptor, root_basename.c_str(),
                &root_after, AT_SYMLINK_NOFOLLOW) != 0 ||
      !same_inode(root_opened, root_after))
    fail("launch_attestation_file_replaced");
  return bytes;
}
std::string fresh_nonce(std::string_view session, std::uint64_t sequence) {
  std::array<unsigned char, 32U> random{};
#if defined(__APPLE__)
  ::arc4random_buf(random.data(), random.size());
#elif defined(__linux__)
  if (::getrandom(random.data(), random.size(), 0) != static_cast<ssize_t>(random.size()))
    fail("nonce_entropy_unavailable");
#else
  fail("nonce_entropy_unavailable");
#endif
  const std::string_view entropy(reinterpret_cast<const char*>(random.data()), random.size());
  return sha256_hex(std::string(session) + ':' + std::to_string(sequence) + ':' +
                    std::string(entropy));
}
JsonValue json_text(std::string value) { return JsonValue(std::move(value)); }
std::string queue_reason(ExecutorQueueKind queue, bool attempted) {
  if (attempted) return "post_broker_overflow_ambiguous";
  switch (queue) {
    case ExecutorQueueKind::MarketReceive: return "market_data_untrustworthy";
    case ExecutorQueueKind::StrategyReceive: return "strategy_receive_overflow";
    case ExecutorQueueKind::RiskWork: return "risk_work_overflow";
    case ExecutorQueueKind::BrokerSubmission: return "broker_submission_overflow";
    case ExecutorQueueKind::BrokerUpdate: return "broker_update_overflow";
    case ExecutorQueueKind::LedgerCommand: return "ledger_command_overflow";
    case ExecutorQueueKind::OutboundEvent: return "outbound_event_overflow";
    case ExecutorQueueKind::Count: break;
  }
  return "queue_invalid";
}
bool unusable_book(const StrategyBookObservation& book) {
  static const std::set<std::string> fatal_flags = {
      "stale", "crossed_book", "source_sequence_unavailable", "unusable"};
  return std::any_of(book.quality_flags.begin(), book.quality_flags.end(),
                     [&](const std::string& flag) { return fatal_flags.contains(flag); });
}
std::optional<std::filesystem::path> exact_option(const std::vector<std::string>& arguments,
                                                  std::string_view wanted) {
  if (arguments.size() != 2U || arguments[0] != wanted || arguments[1].empty()) return std::nullopt;
  std::filesystem::path path(arguments[1]);
  if (!path.is_absolute() || path.lexically_normal() != path) return std::nullopt;
  return path;
}

void validate_paper_model_bytes(std::string_view bytes) {
  try {
    const auto document = parse_json(bytes, 16U * 1024U);
    if (canonical_json(document) != bytes) fail("paper_model_noncanonical");
    const auto& object = json_object(document, "paper_model");
    exact(object, {"model", "schema_version"});
    if (text(object, "schema_version", 16U) != "1.0.0" ||
        text(object, "model", 32U) != "d51_proxy_v1") fail("paper_model_invalid");
  } catch (const IpcProtocolError&) { throw; }
  catch (const JsonError&) { fail("paper_model_malformed"); }
}

std::string event_text(const ExecutionEvent& event, std::string_view key,
                       std::size_t maximum = 192U) {
  const auto found = event.payload.find(key);
  if (found == event.payload.end()) fail("paper_recovery_missing_field");
  try {
    const auto& value = json_string(found->second, key);
    if (value.empty() || value.size() > maximum) fail("paper_recovery_invalid_field");
    return value;
  } catch (const JsonError&) { fail("paper_recovery_invalid_field"); }
}
std::uint64_t event_number(const ExecutionEvent& event, std::string_view key) {
  const auto found = event.payload.find(key);
  if (found == event.payload.end()) fail("paper_recovery_missing_field");
  try { return json_uint64(found->second, key); }
  catch (const JsonError&) { fail("paper_recovery_invalid_field"); }
}
std::int64_t event_timestamp(const ExecutionEvent& event, std::string_view key) {
  const auto found = event.payload.find(key);
  if (found == event.payload.end()) fail("paper_recovery_missing_field");
  try { return json_int64(found->second, key); }
  catch (const JsonError&) { fail("paper_recovery_invalid_field"); }
}
void capture_paper_sequence(std::string_view value, std::uint64_t& sequence) {
  static constexpr std::string_view prefix = "paper-";
  if (!value.starts_with(prefix) || value.size() != prefix.size() + 8U) return;
  std::uint64_t parsed{};
  const auto* first = value.data() + static_cast<std::ptrdiff_t>(prefix.size());
  const auto* last = value.data() + static_cast<std::ptrdiff_t>(value.size());
  const auto result = std::from_chars(first, last, parsed);
  if (result.ec != std::errc{} || result.ptr != last) fail("paper_recovery_sequence_invalid");
  sequence = std::max(sequence, parsed);
}
PaperBrokerRecovery recover_paper_state(const LedgerVerificationResult& verification,
                                        PaperFillModel model) {
  if (!verification.clean() || verification.records.size() != verification.verified_records)
    fail("paper_recovery_ledger_unverified");
  PaperBrokerRecovery result;
  result.snapshot.model = model;
  result.snapshot.health = BrokerSessionHealth::Ready;
  result.replayed.broker_source = "paper";
  result.replayed.position_provenance = "proxy";
  result.replayed.reconstructed = replay_ledger(verification);
  std::map<std::string, RoutingRecord> routes;
  std::map<std::string, BrokerOrderRequest> requests;
  std::map<std::string, std::uint64_t> prior_filled;
  std::map<std::string, std::string> intent_instruments;
  std::map<std::string, PaperMarkSnapshot> accounting_marks;
  std::map<std::string, std::int64_t> accounting_positions;
  std::int64_t accounting_cash = 0;
  std::int64_t accounting_peak = 0;
  bool accounting_valid = true;
  bool pending_mark_without_fill = false;
  const auto update_accounting_peak = [&] {
    if (!accounting_valid) return;
    std::int64_t equity = accounting_cash;
    for (const auto& [canonical, quantity] : accounting_positions) {
      if (quantity == 0) continue;
      const auto mark = accounting_marks.find(canonical);
      if (mark == accounting_marks.end()) { accounting_valid = false; return; }
      const auto price = quantity > 0
          ? mark->second.best_bid_paise.value_or(mark->second.last_trade_paise.value_or(0U))
          : mark->second.best_ask_paise.value_or(mark->second.last_trade_paise.value_or(0U));
      if (price == 0U || quantity == std::numeric_limits<std::int64_t>::min()) {
        accounting_valid = false; return;
      }
      const auto absolute = static_cast<std::uint64_t>(quantity < 0 ? -quantity : quantity);
      if (absolute != 0U &&
          price > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) / absolute) {
        accounting_valid = false; return;
      }
      const auto notional = static_cast<std::int64_t>(absolute * price);
      if ((quantity > 0 && equity > std::numeric_limits<std::int64_t>::max() - notional) ||
          (quantity < 0 && equity < std::numeric_limits<std::int64_t>::min() + notional)) {
        accounting_valid = false; return;
      }
      equity += quantity > 0 ? notional : -notional;
    }
    accounting_peak = std::max(accounting_peak, equity);
  };
  for (const auto& record : verification.records) {
    const auto& event = record.event;
    const bool fill_event = event.event_type == "partially_filled" || event.event_type == "filled";
    if (pending_mark_without_fill && event.event_type != "market_observation_accepted" &&
        !fill_event) {
      update_accounting_peak();
      pending_mark_without_fill = false;
    }
    if (const auto found = event.payload.find("update_id"); found != event.payload.end()) {
      try { capture_paper_sequence(json_string(found->second, "update_id"), result.snapshot.sequence); }
      catch (const JsonError&) { fail("paper_recovery_invalid_update_id"); }
    }
    if (const auto found = event.payload.find("broker_order_id"); found != event.payload.end()) {
      try { capture_paper_sequence(json_string(found->second, "broker_order_id"),
                                   result.snapshot.sequence); }
      catch (const JsonError&) { fail("paper_recovery_invalid_broker_id"); }
    }
    if (event.event_type == "market_observation_accepted") {
      if (pending_mark_without_fill) update_accounting_peak();
      const auto nullable_price = [&](std::string_view key) -> std::optional<std::uint64_t> {
        const auto found = event.payload.find(key);
        if (found == event.payload.end()) fail("paper_recovery_missing_mark");
        if (std::holds_alternative<std::nullptr_t>(found->second.value)) return std::nullopt;
        try { return json_uint64(found->second, key); }
        catch (const JsonError&) { fail("paper_recovery_invalid_mark"); }
      };
      PaperMarkSnapshot mark;
      mark.canonical_instrument_id = event_text(event, "canonical_instrument_id", 192U);
      mark.best_bid_paise = nullable_price("best_bid_paise");
      mark.best_ask_paise = nullable_price("best_ask_paise");
      mark.last_trade_paise = nullable_price("last_trade_paise");
      mark.timestamp_ns = event_timestamp(event, "receive_timestamp_ns");
      accounting_marks.insert_or_assign(mark.canonical_instrument_id, mark);
      result.snapshot.latest_observation_ns =
          std::max(result.snapshot.latest_observation_ns, mark.timestamp_ns);
      pending_mark_without_fill = true;
    } else if (event.event_type == "intent_received") {
      if (!event.intent_id) fail("paper_recovery_missing_intent_id");
      intent_instruments.insert_or_assign(
          *event.intent_id, event_text(event, "canonical_instrument_id", 192U));
    } else if (event.event_type == "mapping_validated") {
      if (!event.internal_order_id) fail("paper_recovery_missing_order_id");
      RoutingRecord route;
      if (const auto canonical = event.payload.find("canonical_instrument_id");
          canonical != event.payload.end()) {
        route.canonical_instrument_id = event_text(event, "canonical_instrument_id", 192U);
      } else {
        if (!event.intent_id) fail("paper_recovery_missing_intent_id");
        const auto found = intent_instruments.find(*event.intent_id);
        if (found == intent_instruments.end()) fail("paper_recovery_missing_instrument");
        route.canonical_instrument_id = found->second;
      }
      route.instrument_token = event_text(event, "instrument_token", 64U);
      route.exchange_segment = event_text(event, "exchange_segment", 16U);
      route.trading_symbol = event_text(event, "trading_symbol", 128U);
      route.lot_size = event_number(event, "lot_size");
      route.tick_size_paise = event_number(event, "tick_size_paise");
      routes.insert_or_assign(*event.internal_order_id, std::move(route));
    } else if (event.event_type == "submission_started") {
      if (!event.internal_order_id || !event.intent_id) fail("paper_recovery_missing_order_id");
      const auto route = routes.find(*event.internal_order_id);
      if (route == routes.end()) fail("paper_recovery_missing_route");
      BrokerOrderRequest request;
      request.internal_order_id = *event.internal_order_id;
      request.intent_id = *event.intent_id;
      request.route = route->second;
      request.side = event_text(event, "side", 4U) == "BUY" ? OrderSide::Buy : OrderSide::Sell;
      request.quantity = event_number(event, "quantity");
      request.limit_price_paise = event_number(event, "limit_price_paise");
      request.submitted_at_ns = event.timestamp_ns;
      request.baseline_cumulative_volume = event_number(event, "baseline_cumulative_volume");
      requests.insert_or_assign(*event.internal_order_id, std::move(request));
    } else if (event.event_type == "partially_filled" || event.event_type == "filled") {
      if (!event.internal_order_id) fail("paper_recovery_missing_order_id");
      const auto request = requests.find(*event.internal_order_id);
      if (request == requests.end()) fail("paper_recovery_missing_request");
      const auto cumulative = event_number(event, "cumulative_filled_quantity");
      auto& previous = prior_filled[*event.internal_order_id];
      if (cumulative <= previous) fail("paper_recovery_fill_sequence_invalid");
      auto provenance = event_text(event, "provenance", 24U);
      if (provenance == "simulated") provenance = "simulated_proxy";
      result.snapshot.fills.push_back(
          {event_text(event, "update_id", 128U), *event.internal_order_id,
           request->second.route.canonical_instrument_id, request->second.route.instrument_token,
           cumulative, cumulative - previous, event_number(event, "fill_price_paise"),
           event_timestamp(event, "evidence_timestamp_ns"), std::move(provenance)});
      const auto fill_quantity = cumulative - previous;
      const auto fill_price = event_number(event, "fill_price_paise");
      if (fill_quantity > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) ||
          fill_price >
              static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) /
                  fill_quantity) {
        accounting_valid = false;
      } else {
        const auto quantity = static_cast<std::int64_t>(fill_quantity);
        const auto notional = static_cast<std::int64_t>(fill_quantity * fill_price);
        auto& position = accounting_positions[request->second.route.canonical_instrument_id];
        const auto position_delta = request->second.side == OrderSide::Buy ? quantity : -quantity;
        const auto cash_delta = request->second.side == OrderSide::Buy ? -notional : notional;
        if ((position_delta > 0 && position > std::numeric_limits<std::int64_t>::max() - position_delta) ||
            (position_delta < 0 && position < std::numeric_limits<std::int64_t>::min() - position_delta) ||
            (cash_delta > 0 && accounting_cash > std::numeric_limits<std::int64_t>::max() - cash_delta) ||
            (cash_delta < 0 && accounting_cash < std::numeric_limits<std::int64_t>::min() - cash_delta)) {
          accounting_valid = false;
        } else {
          position += position_delta;
          accounting_cash += cash_delta;
          update_accounting_peak();
          pending_mark_without_fill = false;
        }
      }
      previous = cumulative;
    }
  }
  if (pending_mark_without_fill) update_accounting_peak();
  result.snapshot.cash_paise = accounting_cash;
  result.snapshot.peak_equity_paise = accounting_peak;
  result.snapshot.pnl_valid = accounting_valid;
  for (auto& [unused, mark] : accounting_marks) {
    (void)unused;
    result.snapshot.marks.push_back(std::move(mark));
  }
  for (const auto& [order_id, aggregate] : result.replayed.reconstructed.orders) {
    const auto request = requests.find(order_id);
    if (request == requests.end()) fail("paper_recovery_missing_request");
    auto restored_request = request->second;
    restored_request.quantity = aggregate.effective_quantity;
    restored_request.limit_price_paise = aggregate.limit_price_paise;
    std::string state;
    switch (aggregate.state) {
      case OrderState::Acknowledged: state = "working"; break;
      case OrderState::PartiallyFilled: state = "partially_filled"; break;
      case OrderState::Filled: state = "filled"; break;
      case OrderState::Cancelled: state = "cancelled"; break;
      case OrderState::Rejected: state = "rejected"; break;
      case OrderState::AmbiguousSubmission: state = "ambiguous"; break;
      default: fail("paper_recovery_incomplete_mutation");
    }
    result.snapshot.requests.push_back(restored_request);
    result.snapshot.orders.push_back(
        {order_id, aggregate.canonical_instrument_id, restored_request.route.instrument_token,
         aggregate.side, aggregate.effective_quantity, aggregate.limit_price_paise,
         aggregate.cumulative_filled_quantity, std::move(state), "simulated_proxy"});
    result.replayed.known_instruments.insert(aggregate.canonical_instrument_id);
  }
  for (const auto& [canonical, quantity] : result.replayed.reconstructed.positions) {
    const auto order = std::find_if(
        result.snapshot.orders.begin(), result.snapshot.orders.end(),
        [&](const BrokerOrderSnapshot& item) { return item.canonical_instrument_id == canonical; });
    if (order == result.snapshot.orders.end()) fail("paper_recovery_position_route_missing");
    result.snapshot.positions.push_back(
        {canonical, order->instrument_token, quantity, "simulated_proxy"});
  }
  result.replayed.orders = result.snapshot.orders;
  result.replayed.fills = result.snapshot.fills;
  result.replayed.positions = result.snapshot.positions;
  return result;
}

void reject_replayed_launch_attestation(const LedgerVerificationResult& verification,
                                        const SessionLaunchEvidence& evidence) {
  if (!verification.clean()) fail("event_ledger_unverified");
  for (const auto& record : verification.records) {
    if (record.event.event_type != "session_started") continue;
    const auto invocation = record.event.payload.find("invocation_id");
    const auto digest_value = record.event.payload.find("launch_attestation_digest");
    try {
      if ((invocation != record.event.payload.end() &&
           json_string(invocation->second, "invocation_id") == evidence.invocation_id) ||
          (digest_value != record.event.payload.end() &&
           constant_time_equal(json_string(digest_value->second, "launch_attestation_digest"),
                               evidence.launch_attestation_digest)))
        fail("launch_attestation_replayed");
    } catch (const JsonError&) {
      fail("launch_attestation_ledger_evidence_invalid");
    }
  }
}

class RuntimeClock final : public SessionClock {
 public:
  std::int64_t now_ns() const noexcept override {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
  }
};

class RuntimeResolver final : public SessionRoutingResolver {
 public:
  RuntimeResolver(InstrumentResolver resolver, std::string trading_date,
                  std::int64_t mapping_timestamp_ns)
      : resolver_(std::move(resolver)), trading_date_(std::move(trading_date)),
        mapping_timestamp_ns_(mapping_timestamp_ns) {}
  ResolutionResult resolve(std::string_view id) const override { return resolver_.resolve(id); }
  std::string_view snapshot_digest() const noexcept override { return resolver_.snapshot_digest(); }
  bool valid_for_trading_date(std::string_view date) const noexcept override {
    return date == trading_date_;
  }
  std::optional<std::int64_t> mapping_timestamp_ns() const noexcept override {
    return mapping_timestamp_ns_;
  }
 private:
  InstrumentResolver resolver_;
  std::string trading_date_;
  std::int64_t mapping_timestamp_ns_{};
};

volatile std::sig_atomic_t runtime_stop_requested = 0;
void runtime_signal_handler(int) { runtime_stop_requested = 1; }
}

PaperBrokerRecovery recover_paper_broker(const LedgerVerificationResult& verification,
                                         PaperFillModel model) {
  return recover_paper_state(verification, model);
}

ExecutorConfiguration parse_executor_configuration(std::string_view bytes) {
  try {
    const auto document = parse_json(bytes, kMaximumIpcPayloadBytes);
    if (canonical_json(document) != bytes) fail("config_noncanonical");
    const auto& object = json_object(document, "executor_configuration");
    exact(object, {"configuration_digest", "configuration_version", "execution_session_id",
                   "expected_cli_release_digest", "expected_deployment_manifest_digest",
                   "expected_executor_build_digest", "expected_strategy_id", "io_deadline_ms",
                   "launch_attestation_root", "ledger_path", "market_socket_basename",
                   "market_peer_identity", "maximum_packet_bytes", "mode", "paper_model_path",
                   "maximum_launch_attestation_age_ns", "protected_artifact_root",
                   "queue_capacities", "reconnect_window_ms",
                   "required_initial_observation_freshness_ns", "risk_configuration_path",
                   "routing_manifest", "routing_snapshot", "runtime_directory", "schema_version",
                   "shutdown_deadline_ms", "strategy_peer_identity", "strategy_socket_basename",
                   "trading_date"});
    ExecutorConfiguration result;
    result.schema_version = text(object, "schema_version", 16U);
    result.configuration_version = text(object, "configuration_version", 64U);
    result.configuration_digest = text(object, "configuration_digest", 64U);
    auto digest_document = document;
    auto& digest_object = std::get<JsonObject>(digest_document.value);
    digest_object.erase("configuration_digest");
    if (!constant_time_equal(result.configuration_digest,
                             sha256_hex(canonical_json(digest_document))))
      fail("config_digest_mismatch");
    result.mode = text(object, "mode", 16U); result.trading_date = text(object, "trading_date", 10U);
    result.runtime_directory = protected_path(object, "runtime_directory");
    result.protected_artifact_root = protected_path(object, "protected_artifact_root");
    result.market_socket_basename = text(object, "market_socket_basename", 80U);
    result.strategy_socket_basename = text(object, "strategy_socket_basename", 80U);
    result.maximum_packet_bytes = number(object, "maximum_packet_bytes");
    result.io_deadline_ms = signed_number(object, "io_deadline_ms");
    result.reconnect_window_ms = signed_number(object, "reconnect_window_ms");
    result.shutdown_deadline_ms = signed_number(object, "shutdown_deadline_ms");
    result.execution_session_id = text(object, "execution_session_id", 64U);
    result.expected_strategy_id = text(object, "expected_strategy_id", 64U);
    result.routing_snapshot = protected_path(object, "routing_snapshot");
    result.routing_manifest = protected_path(object, "routing_manifest");
    result.ledger_path = protected_path(object, "ledger_path");
    result.launch_attestation_root = protected_path(object, "launch_attestation_root");
    result.expected_cli_release_digest = text(object, "expected_cli_release_digest", 64U);
    result.expected_deployment_manifest_digest =
        text(object, "expected_deployment_manifest_digest", 64U);
    result.expected_executor_build_digest = text(object, "expected_executor_build_digest", 64U);
    result.maximum_launch_attestation_age_ns =
        signed_number(object, "maximum_launch_attestation_age_ns");
    result.risk_configuration_path = protected_path(object, "risk_configuration_path");
    result.paper_model_path = protected_path(object, "paper_model_path");
    result.required_initial_observation_freshness_ns =
        signed_number(object, "required_initial_observation_freshness_ns");
    result.market_peer_identity = peer_identity(object, "market_peer_identity",
                                                PeerRole::MarketPublisher,
                                                result.market_peer_configuration_path);
    result.strategy_peer_identity = peer_identity(object, "strategy_peer_identity",
                                                  PeerRole::StrategyClient,
                                                  result.strategy_peer_configuration_path);
    const auto& capacities = json_object(required(object, "queue_capacities"), "queue_capacities");
    exact(capacities, {"broker_submission", "broker_update", "ledger_command", "market_receive",
                       "outbound_event", "risk_work", "strategy_receive"});
    const std::array<std::string_view, 7> names = {"market_receive", "strategy_receive", "risk_work",
      "broker_submission", "broker_update", "ledger_command", "outbound_event"};
    for (std::size_t index = 0; index < names.size(); ++index)
      result.queue_capacities[index] = number(capacities, names[index]);
    if (result.schema_version != "1.0.0" || result.mode != "shadow" ||
        !digest(result.configuration_digest) || !digest(result.expected_cli_release_digest) ||
        !digest(result.expected_deployment_manifest_digest) ||
        !digest(result.expected_executor_build_digest) ||
        !is_canonical_uuid(result.execution_session_id) || result.maximum_packet_bytes == 0U ||
        result.maximum_packet_bytes > kMaximumIpcPayloadBytes || result.io_deadline_ms <= 0 ||
        result.reconnect_window_ms <= 0 || result.shutdown_deadline_ms <= 0 ||
        result.reconnect_window_ms < result.io_deadline_ms ||
        result.shutdown_deadline_ms < result.io_deadline_ms ||
        result.required_initial_observation_freshness_ns <= 0 ||
        result.maximum_launch_attestation_age_ns <= 0 ||
        std::any_of(result.queue_capacities.begin(), result.queue_capacities.end(),
                    [](std::size_t value) { return value == 0U || value > 65'536U; }))
      fail("config_invalid");
    result.market_peer_identity.execution_session_id = result.execution_session_id;
    result.strategy_peer_identity.execution_session_id = result.execution_session_id;
    result.protected_artifact_descriptor =
        open_protected_directory(result.protected_artifact_root);
    if (!socket_basename(result.market_socket_basename) ||
        !socket_basename(result.strategy_socket_basename) ||
        result.market_socket_basename == result.strategy_socket_basename)
      fail("config_protected_root_invalid");
    for (const auto& path : {result.routing_snapshot, result.routing_manifest, result.ledger_path,
                             result.launch_attestation_root,
                             result.risk_configuration_path, result.paper_model_path,
                             result.market_peer_configuration_path,
                             result.strategy_peer_configuration_path})
      if (!beneath(path, result.protected_artifact_root)) fail("config_path_outside_root");
    if (result.ledger_path.parent_path() != result.protected_artifact_root)
      fail("config_ledger_not_rooted");
    if (result.launch_attestation_root.parent_path() != result.protected_artifact_root)
      fail("config_attestation_root_not_rooted");
    for (const auto& [path, expected_digest] :
         std::array<std::pair<std::filesystem::path, std::string>, 2U>{
             std::pair{result.market_peer_configuration_path,
                       result.market_peer_identity.configuration_digest},
             std::pair{result.strategy_peer_configuration_path,
                       result.strategy_peer_identity.configuration_digest}}) {
      const auto peer_bytes = read_protected_beneath(result, path, 64U * 1024U);
      try {
        const auto peer_document = parse_json(peer_bytes, 64U * 1024U);
        if (canonical_json(peer_document) != peer_bytes ||
            !constant_time_equal(expected_digest, sha256_hex(peer_bytes)))
          fail("config_peer_configuration_digest_mismatch");
      } catch (const JsonError&) { fail("config_peer_configuration_invalid"); }
    }
    struct stat attestation_root{};
    if (::fstatat(*result.protected_artifact_descriptor,
                  result.launch_attestation_root.filename().c_str(), &attestation_root,
                  AT_SYMLINK_NOFOLLOW) != 0 ||
        !S_ISDIR(attestation_root.st_mode) || attestation_root.st_uid != ::geteuid() ||
        (attestation_root.st_mode & 07777U) != 0700U)
      fail("config_attestation_root_invalid");
    const int attestation_descriptor = ::openat(*result.protected_artifact_descriptor,
        result.launch_attestation_root.filename().c_str(),
        O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
    if (attestation_descriptor < 0 ||
        !safe_directory_descriptor(attestation_descriptor, true)) {
      if (attestation_descriptor >= 0) (void)::close(attestation_descriptor);
      fail("config_attestation_root_invalid");
    }
    result.launch_attestation_root_descriptor = std::shared_ptr<int>(
        new int(attestation_descriptor), [](int* value) {
          if (value != nullptr) {
            if (*value >= 0) (void)::close(*value);
            delete value;
          }
        });
    return result;
  } catch (const IpcProtocolError&) { throw; }
  catch (const JsonError&) { fail("config_malformed"); }
}

ExecutorConfiguration load_executor_configuration(const std::filesystem::path& path) {
  return parse_executor_configuration(read_protected(path, kMaximumIpcPayloadBytes));
}

std::string running_executable_digest() {
  int descriptor = -1;
#if defined(__linux__)
  descriptor = ::open("/proc/self/exe", O_RDONLY | O_CLOEXEC);
#elif defined(__APPLE__)
  std::uint32_t size = 0U;
  (void)::_NSGetExecutablePath(nullptr, &size);
  if (size == 0U || size > 32U * 1024U) fail("executor_executable_path_invalid");
  std::string path(size, '\0');
  if (::_NSGetExecutablePath(path.data(), &size) != 0)
    fail("executor_executable_path_invalid");
  path.resize(std::char_traits<char>::length(path.c_str()));
  descriptor = ::open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
#else
  fail("executor_platform_unsupported");
#endif
  if (descriptor < 0) fail("executor_executable_unreadable");
  struct Guard { int value; ~Guard() { if (value >= 0) (void)::close(value); } } guard{descriptor};
  struct stat before{};
  constexpr std::uint64_t maximum_executable_bytes = 256U * 1024U * 1024U;
  if (::fstat(descriptor, &before) != 0 || !S_ISREG(before.st_mode) || before.st_size <= 0 ||
      static_cast<std::uint64_t>(before.st_size) > maximum_executable_bytes)
    fail("executor_executable_unsafe");
  std::string bytes(static_cast<std::size_t>(before.st_size), '\0');
  std::size_t offset = 0U;
  while (offset < bytes.size()) {
    const auto count = ::read(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) fail("executor_executable_changed");
    offset += static_cast<std::size_t>(count);
  }
  struct stat after{};
  if (::fstat(descriptor, &after) != 0 || !same_inode(before, after))
    fail("executor_executable_changed");
  return sha256_hex(bytes);
}

SessionLaunchEvidence validate_launch_attestation(const ExecutorConfiguration& configuration,
                                                  const std::filesystem::path& path,
                                                  std::int64_t now_ns) {
  const auto bytes = read_launch_attestation(configuration, path);
  try {
    const auto document = parse_json(bytes, 32U * 1024U);
    if (canonical_json(document) != bytes) fail("launch_attestation_noncanonical");
    const auto& object = json_object(document, "launch_attestation");
    exact(object, {"cli_release_digest", "confirmation_type", "deployment_manifest_digest",
                   "device_id", "execution_session_id", "executor_build_digest", "invocation_id",
                   "launch_timestamp_ns", "operator_id", "public_key_fingerprint",
                   "requested_mode", "schema_version"});
    SessionLaunchEvidence result;
    result.launch_attestation_digest = sha256_hex(bytes);
    result.cli_release_digest = text(object, "cli_release_digest", 64U);
    result.confirmation_type = text(object, "confirmation_type", 64U);
    result.deployment_manifest_digest = text(object, "deployment_manifest_digest", 64U);
    result.device_id = text(object, "device_id", 128U);
    result.execution_session_id = text(object, "execution_session_id", 64U);
    result.executor_build_digest = text(object, "executor_build_digest", 64U);
    result.invocation_id = text(object, "invocation_id", 64U);
    result.launch_timestamp_ns = signed_number(object, "launch_timestamp_ns");
    result.operator_id = text(object, "operator_id", 128U);
    result.public_key_fingerprint = text(object, "public_key_fingerprint", 128U);
    result.requested_mode = text(object, "requested_mode", 16U);
    if (text(object, "schema_version", 16U) != "1.0.0" ||
        result.requested_mode != "shadow" ||
        result.confirmation_type != "SHAURYA_SHADOW_LAUNCH" ||
        result.execution_session_id != configuration.execution_session_id ||
        !is_canonical_uuid(result.invocation_id) || path.stem().string() != result.invocation_id ||
        now_ns <= 0 || result.launch_timestamp_ns <= 0 || result.launch_timestamp_ns > now_ns ||
        now_ns - result.launch_timestamp_ns > configuration.maximum_launch_attestation_age_ns ||
        !constant_time_equal(result.cli_release_digest,
                             configuration.expected_cli_release_digest) ||
        !constant_time_equal(result.deployment_manifest_digest,
                             configuration.expected_deployment_manifest_digest) ||
        !constant_time_equal(result.executor_build_digest,
                             configuration.expected_executor_build_digest))
      fail("launch_attestation_invalid");
    return result;
  } catch (const IpcProtocolError&) { throw; }
  catch (const JsonError&) { fail("launch_attestation_malformed"); }
}

Executor::Executor(ExecutorConfiguration configuration, ExecutionSession& session,
                   ExecutionLedger& durable_event_ledger, SessionClock& clock)
    : configuration_(std::move(configuration)), session_(session),
      durable_event_ledger_(durable_event_ledger), clock_(clock),
      queues_{BoundedChannel<ExecutorStageMessage>(configuration_.queue_capacities[0]),
              BoundedChannel<ExecutorStageMessage>(configuration_.queue_capacities[1]),
              BoundedChannel<ExecutorStageMessage>(configuration_.queue_capacities[2]),
              BoundedChannel<ExecutorStageMessage>(configuration_.queue_capacities[3]),
              BoundedChannel<ExecutorStageMessage>(configuration_.queue_capacities[4]),
              BoundedChannel<ExecutorStageMessage>(configuration_.queue_capacities[5]),
              BoundedChannel<ExecutorStageMessage>(configuration_.queue_capacities[6])} {
  const auto verified = durable_event_ledger_.verify(LedgerVerificationMode::RetainRecords);
  if (!verified.clean() || verified.verified_records != durable_event_ledger_.last_sequence())
    fail("event_ledger_unverified");
  for (const auto& record : verified.records) {
    if (record.event.execution_session_id != configuration_.execution_session_id ||
        (record.event.strategy_id &&
         *record.event.strategy_id != configuration_.expected_strategy_id))
      fail("event_ledger_scope_invalid");
    if (record.event.strategy_run_id) {
      if (bound_strategy_run_id_ && *bound_strategy_run_id_ != *record.event.strategy_run_id)
        fail("event_ledger_strategy_run_scope_invalid");
      bound_strategy_run_id_ = *record.event.strategy_run_id;
    }
    if (record.event.event_type == "market_observation_accepted") {
      const auto found = record.event.payload.find("source_sequence");
      if (found == record.event.payload.end()) fail("source_sequence_evidence_missing");
      std::uint64_t sequence = 0U;
      try { sequence = json_uint64(found->second, "source_sequence"); }
      catch (const JsonError&) { fail("source_sequence_evidence_invalid"); }
      if (sequence != observation_sequence_ + 1U)
        fail("source_sequence_evidence_invalid");
      observation_sequence_ = sequence;
    }
    replay_.append({record.sequence, record.event.execution_session_id,
                    configuration_.expected_strategy_id, record.event.to_json()});
  }
  event_sequence_ = durable_event_ledger_.last_sequence();
  session_.set_stage_coordinator(this);
  ledger_worker_ = std::thread([this] { ledger_worker_loop(); });
}

Executor::~Executor() {
  ledger_worker_stop_.store(true);
  if (ledger_worker_.joinable()) ledger_worker_.join();
  session_.set_stage_coordinator(nullptr);
}

void Executor::authenticate_peer(const ExpectedPeerIdentity& expected,
                                 const IpcHandshake& handshake,
                                 const PeerInspector& inspector,
                                 int accepted_socket,
                                 bool production_required) {
  const auto evidence = inspector.inspect(accepted_socket);
  validate_peer_identity(expected, handshake.bindings, evidence, production_required);
  if (expected.role == PeerRole::StrategyClient &&
      (!handshake.strategy_id ||
       !constant_time_equal(*handshake.strategy_id, configuration_.expected_strategy_id)))
    fail("peer_strategy_identity_mismatch");
  const std::lock_guard<std::mutex> guard(state_mutex_);
  if (expected.role == PeerRole::MarketPublisher) {
    market_peer_ = evidence; market_authenticated_ = true;
  } else {
    strategy_peer_ = evidence; strategy_authenticated_ = true;
  }
}
void Executor::validate_peer_connection(PeerRole role, const PeerInspector& inspector,
                                        int accepted_socket) const {
  const auto current = inspector.inspect(accepted_socket);
  const std::lock_guard<std::mutex> guard(state_mutex_);
  const auto& authenticated = role == PeerRole::MarketPublisher ? market_peer_ : strategy_peer_;
  if (!authenticated) fail("peer_not_authenticated");
  validate_peer_continuity(*authenticated, current);
}
MarketAcceptResult Executor::accept_market(IpcEnvelope envelope) {
  if (!submit_market_from_reader(std::move(envelope))) {
    record_reader_overflow(ExecutorQueueKind::MarketReceive);
    return {};
  }
  return process_next_market();
}

bool Executor::submit_market_from_reader(IpcEnvelope envelope) {
  authorize_inbound(PeerRole::MarketPublisher, envelope, configuration_.execution_session_id,
                    configuration_.expected_strategy_id);
  (void)StrategyBookObservation::parse(envelope.canonical_payload);
  return queues_[static_cast<std::size_t>(ExecutorQueueKind::MarketReceive)]
      .try_push(std::move(envelope));
}

MarketAcceptResult Executor::process_next_market() {
  const std::lock_guard<std::mutex> guard(state_mutex_);
  MarketAcceptResult result;
  auto received = queues_[static_cast<std::size_t>(ExecutorQueueKind::MarketReceive)].try_pop();
  if (!received) return result;
  auto* received_envelope = std::get_if<IpcEnvelope>(&*received);
  if (!received_envelope) fail("market_receive_stage_type_invalid");
  auto envelope = std::move(*received_envelope);
  if (!market_authenticated_) {
    stop_once("market_publisher_not_authenticated"); return result;
  }
  const auto book = StrategyBookObservation::parse(envelope.canonical_payload);
  if (unusable_book(book)) {
    stop_once("market_observation_unusable");
    return result;
  }
  auto observation = book.derive_market_observation();
  const auto now = clock_.now_ns();
  if (now < observation.receive_timestamp_ns) {
    stop_once("market_observation_stale"); return result;
  }
  const auto age = now - observation.receive_timestamp_ns;
  if (configuration_.required_initial_observation_freshness_ns <= 0 ||
      age > configuration_.required_initial_observation_freshness_ns) {
    stop_once("market_observation_stale"); return result;
  }
  const auto ledger_before = durable_event_ledger_.last_sequence();
  if (observation_sequence_ == std::numeric_limits<std::uint64_t>::max()) {
    stop_once("source_sequence_exhausted");
    return result;
  }
  const auto source_sequence = observation_sequence_ + 1U;
  const auto source_digest = sha256_hex(envelope.canonical_payload);
  if (!session_.record_market_observation_accepted(source_sequence, source_digest,
                                                    observation)) {
    stop_once("market_observation_evidence_not_durable");
    return result;
  }
  observation_sequence_ = source_sequence;
  last_observation_receive_ns_ = book.receive_timestamp_ns;
  last_observation_activity_ = std::chrono::steady_clock::now();
  broker_update_dispatched_in_cycle_ = false;
  session_.accept_observation(std::move(observation));
  auto& broker_updates = queues_[static_cast<std::size_t>(ExecutorQueueKind::BrokerUpdate)];
  while (auto update_message = broker_updates.try_pop()) {
    auto* update = std::get_if<BrokerUpdateEnvelope>(&*update_message);
    if (!update) {
      stop_once("broker_update_stage_type_invalid");
      break;
    }
    if (!session_.accept_broker_update(*update)) break;
  }
  fresh_observation_ = session_.ready();
  envelope.source_sequence = source_sequence;
  envelope.source_digest = source_digest;
  result.execution_events = collect_events_after(ledger_before,
                                                  broker_update_dispatched_in_cycle_);
  const auto generated = durable_event_ledger_.last_sequence() - ledger_before;
  if (result.execution_events.size() == generated && !safety_reason_)
    result.strategy_book = std::move(envelope);
  return result;
}

std::vector<IpcEnvelope> Executor::accept_intent(IpcEnvelope envelope) {
  if (!submit_intent_from_reader(std::move(envelope))) {
    record_reader_overflow(ExecutorQueueKind::StrategyReceive);
    return {};
  }
  std::vector<IpcEnvelope> result = process_next_intent();
  auto risk_events = process_next_risk_work();
  result.insert(result.end(), std::make_move_iterator(risk_events.begin()),
                std::make_move_iterator(risk_events.end()));
  auto broker_events = process_next_broker_submission();
  result.insert(result.end(), std::make_move_iterator(broker_events.begin()),
                std::make_move_iterator(broker_events.end()));
  return result;
}

bool Executor::submit_intent_from_reader(IpcEnvelope envelope) {
  authorize_inbound(PeerRole::StrategyClient, envelope, configuration_.execution_session_id,
                    configuration_.expected_strategy_id);
  if (envelope.kind != IpcMessageKind::OrderIntent) fail("strategy_message_kind_invalid");
  const auto intent = OrderIntent::parse(envelope.canonical_payload);
  if (intent.execution_session_id != configuration_.execution_session_id ||
      intent.strategy_id != configuration_.expected_strategy_id ||
      !envelope.strategy_id || *envelope.strategy_id != intent.strategy_id)
    fail("strategy_intent_binding_mismatch");
  {
    const std::lock_guard<std::mutex> guard(state_mutex_);
    if (bound_strategy_run_id_ && *bound_strategy_run_id_ != intent.strategy_run_id)
      fail("strategy_intent_run_binding_mismatch");
  }
  const auto accepted = queues_[static_cast<std::size_t>(ExecutorQueueKind::StrategyReceive)]
      .try_push(std::move(envelope));
  if (accepted) {
    const std::lock_guard<std::mutex> guard(state_mutex_);
    if (!bound_strategy_run_id_) bound_strategy_run_id_ = intent.strategy_run_id;
  }
  return accepted;
}

std::vector<IpcEnvelope> Executor::process_next_intent() {
  const std::lock_guard<std::mutex> guard(state_mutex_);
  auto received = queues_[static_cast<std::size_t>(ExecutorQueueKind::StrategyReceive)].try_pop();
  if (!received) return {};
  auto* received_envelope = std::get_if<IpcEnvelope>(&*received);
  if (!received_envelope) fail("strategy_receive_stage_type_invalid");
  auto envelope = std::move(*received_envelope);
  if (!strategy_authenticated_ && !stop_requested_.load()) {
    stop_once("strategy_not_authenticated"); return {};
  }
  if (!queues_[static_cast<std::size_t>(ExecutorQueueKind::RiskWork)]
           .try_push(std::move(envelope))) {
    stop_once(queue_reason(ExecutorQueueKind::RiskWork, false));
  }
  return {};
}

std::vector<IpcEnvelope> Executor::process_next_risk_work() {
  (void)check_market_freshness();
  const std::lock_guard<std::mutex> guard(state_mutex_);
  auto work = queues_[static_cast<std::size_t>(ExecutorQueueKind::RiskWork)].try_pop();
  if (!work) return {};
  auto* staged = std::get_if<IpcEnvelope>(&*work);
  if (!staged) {
    stop_once("risk_work_stage_type_invalid");
    return {};
  }
  auto envelope = std::move(*staged);
  const auto intent = OrderIntent::parse(envelope.canonical_payload);
  const auto prior = replay_intent(intent.intent_id);
  if (!prior.empty()) {
    for (const auto& item : prior) {
      const auto event = ExecutionEvent::parse(item.canonical_payload);
      if (event.event_type != "intent_received") continue;
      const auto found = event.payload.find("semantic_fingerprint");
      if (found != event.payload.end() &&
          json_string(found->second, "semantic_fingerprint") == intent.semantic_fingerprint())
        return prior;
    }
  }
  const auto ledger_before = durable_event_ledger_.last_sequence();
  auto prepared = session_.prepare_intent(intent);
  auto events = collect_events_after(ledger_before, false);
  if (!prepared.requires_broker_submission() || safety_reason_) return events;
  if (!queues_[static_cast<std::size_t>(ExecutorQueueKind::BrokerSubmission)]
           .try_push(std::move(prepared))) {
    stop_once(queue_reason(ExecutorQueueKind::BrokerSubmission, false));
  }
  return events;
}

std::vector<IpcEnvelope> Executor::process_next_broker_submission() {
  const std::lock_guard<std::mutex> guard(state_mutex_);
  auto work = queues_[static_cast<std::size_t>(ExecutorQueueKind::BrokerSubmission)].try_pop();
  if (!work) return {};
  auto* prepared = std::get_if<PreparedSessionIntent>(&*work);
  if (!prepared) {
    stop_once("broker_submission_stage_type_invalid");
    return {};
  }
  const auto ledger_before = durable_event_ledger_.last_sequence();
  const auto outcome = session_.submit_prepared(std::move(*prepared));
  return collect_events_after(ledger_before, outcome.broker_result.has_value());
}

void Executor::record_reader_overflow(ExecutorQueueKind queue) {
  const auto ledger_before = durable_event_ledger_.last_sequence();
  {
    const std::lock_guard<std::mutex> guard(state_mutex_);
    stop_once(queue_reason(queue, false));
  }
  static_cast<void>(collect_events_after(ledger_before, false));
}

void Executor::record_peer_disconnect(PeerRole role) {
  const auto ledger_before = durable_event_ledger_.last_sequence();
  {
    const std::lock_guard<std::mutex> guard(state_mutex_);
    if (role == PeerRole::MarketPublisher) market_authenticated_ = false;
    else strategy_authenticated_ = false;
    fresh_observation_ = false;
    stop_once(role == PeerRole::MarketPublisher ? "market_peer_disconnected"
                                                 : "strategy_peer_disconnected");
  }
  static_cast<void>(collect_events_after(ledger_before, false));
}

bool Executor::restore_strategy_authority_after_reconnect() {
  {
    const std::lock_guard<std::mutex> guard(state_mutex_);
    if (!strategy_authenticated_ ||
        safety_reason_ != std::optional<std::string>("strategy_peer_disconnected"))
      return false;
  }
  const auto ledger_before = durable_event_ledger_.last_sequence();
  if (!session_.reconcile_after_strategy_reconnect()) return false;
  static_cast<void>(collect_events_after(ledger_before, false));
  const std::lock_guard<std::mutex> guard(state_mutex_);
  const auto now = clock_.now_ns();
  const auto fresh = market_authenticated_ && last_observation_receive_ns_ &&
                     last_observation_activity_ && now >= *last_observation_receive_ns_ &&
                     now - *last_observation_receive_ns_ <=
                         configuration_.required_initial_observation_freshness_ns &&
                     std::chrono::steady_clock::now() - *last_observation_activity_ <=
                         std::chrono::nanoseconds(
                             configuration_.required_initial_observation_freshness_ns);
  if (!fresh) {
    const auto refusal_before = durable_event_ledger_.last_sequence();
    session_.activate_kill_switch("strategy_reconnect_market_not_fresh");
    static_cast<void>(collect_events_after(refusal_before, false));
    safety_reason_ = "strategy_reconnect_market_not_fresh";
    return false;
  }
  fresh_observation_ = true;
  safety_reason_.reset();
  return true;
}

bool Executor::acknowledge_ledger_boundary(std::uint64_t expected_sequence,
                                           bool broker_attempted) {
  auto& channel = queues_[static_cast<std::size_t>(ExecutorQueueKind::LedgerCommand)];
  auto acknowledgement = std::make_shared<std::promise<bool>>();
  auto result = acknowledgement->get_future();
  if (!channel.try_push(DurableLedgerCommand{expected_sequence, broker_attempted,
                                              acknowledgement})) {
    stop_once(queue_reason(ExecutorQueueKind::LedgerCommand, broker_attempted));
    return false;
  }
  if (result.wait_for(std::chrono::milliseconds(configuration_.io_deadline_ms)) !=
          std::future_status::ready || !result.get()) {
    stop_once(broker_attempted ? "post_broker_ledger_unacknowledged"
                               : "pre_broker_ledger_unacknowledged");
    return false;
  }
  return true;
}

void Executor::ledger_worker_loop() {
  auto& channel = queues_[static_cast<std::size_t>(ExecutorQueueKind::LedgerCommand)];
  while (!ledger_worker_stop_.load()) {
    auto message = channel.try_pop();
    if (!message) {
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
      continue;
    }
    auto* command = std::get_if<DurableLedgerCommand>(&*message);
    if (!command || !command->acknowledgement) continue;
    bool acknowledged = false;
    try {
      const auto verified = durable_event_ledger_.verify();
      acknowledged = verified.clean() &&
                     verified.verified_records == command->expected_sequence &&
                     durable_event_ledger_.last_sequence() == command->expected_sequence;
    } catch (...) {
      acknowledged = false;
    }
    try { command->acknowledgement->set_value(acknowledged); } catch (...) {}
  }
}

bool Executor::reserve_broker_updates(std::size_t maximum_updates) {
  auto& channel = queues_[static_cast<std::size_t>(ExecutorQueueKind::BrokerUpdate)];
  const auto metrics = channel.metrics();
  if (maximum_updates == 0U) return true;
  if (reserved_broker_updates_ != 0U || metrics.depth != 0U ||
      maximum_updates > metrics.capacity) {
    stop_once("broker_update_capacity_unavailable");
    return false;
  }
  for (std::size_t index = 0; index < maximum_updates; ++index) {
    if (!channel.try_push(BrokerUpdateReservation{index + 1U})) {
      release_broker_update_reservations();
      stop_once("broker_update_capacity_unavailable");
      return false;
    }
    ++reserved_broker_updates_;
  }
  return true;
}

bool Executor::dispatch_broker_update(BrokerUpdateEnvelope update) {
  auto& channel = queues_[static_cast<std::size_t>(ExecutorQueueKind::BrokerUpdate)];
  if (reserved_broker_updates_ == 0U ||
      !channel.try_replace_first_if([](const ExecutorStageMessage& message) {
        return std::holds_alternative<BrokerUpdateReservation>(message);
      }, ExecutorStageMessage(std::move(update)))) {
    stop_once("broker_update_reservation_invalid");
    return false;
  }
  --reserved_broker_updates_;
  broker_update_dispatched_in_cycle_ = true;
  return true;
}

void Executor::release_broker_update_reservations() noexcept {
  auto& channel = queues_[static_cast<std::size_t>(ExecutorQueueKind::BrokerUpdate)];
  const auto removed = channel.discard_all_if([](const ExecutorStageMessage& message) {
    return std::holds_alternative<BrokerUpdateReservation>(message);
  });
  if (removed != reserved_broker_updates_) stop_once("broker_update_reservation_invalid");
  reserved_broker_updates_ = 0U;
}

std::vector<IpcEnvelope> Executor::collect_events_after(std::uint64_t sequence,
                                                        bool broker_attempted) {
  const auto verified = durable_event_ledger_.verify(LedgerVerificationMode::RetainRecords);
  if (!verified.clean() || verified.verified_records != durable_event_ledger_.last_sequence() ||
      sequence > verified.verified_records)
    fail("event_ledger_unverified");
  std::vector<IpcEnvelope> emitted;
  for (const auto& record : verified.records) {
    if (record.sequence <= sequence) continue;
    if (record.sequence != event_sequence_ + 1U ||
        record.event.execution_session_id != configuration_.execution_session_id ||
        (record.event.strategy_id &&
         *record.event.strategy_id != configuration_.expected_strategy_id))
      fail("event_ledger_sequence_invalid");
    event_sequence_ = record.sequence;
    const auto bytes = record.event.to_json();
    replay_.append({record.sequence, configuration_.execution_session_id,
                    configuration_.expected_strategy_id, bytes});
    IpcEnvelope outbound{IpcMessageKind::ExecutionEvent, configuration_.execution_session_id,
                         configuration_.expected_strategy_id, std::nullopt, record.sequence, bytes,
                         std::nullopt};
    if (!enqueue(ExecutorQueueKind::OutboundEvent, outbound, broker_attempted)) continue;
    emitted.push_back(std::move(outbound));
  }
  return emitted;
}

std::optional<IpcEnvelope> Executor::pass_stage(ExecutorQueueKind queue, IpcEnvelope envelope,
                                                bool broker_attempted) {
  if (!enqueue(queue, std::move(envelope), broker_attempted)) return std::nullopt;
  auto value = queues_[static_cast<std::size_t>(queue)].try_pop();
  if (!value) {
    stop_once(queue_reason(queue, broker_attempted));
    return std::nullopt;
  }
  auto* staged = std::get_if<IpcEnvelope>(&*value);
  if (!staged) {
    stop_once(queue_reason(queue, broker_attempted));
    return std::nullopt;
  }
  return std::move(*staged);
}

std::vector<IpcEnvelope> Executor::replay_intent(std::string_view intent_id) const {
  const auto verified = durable_event_ledger_.verify(LedgerVerificationMode::RetainRecords);
  if (!verified.clean() || verified.verified_records != durable_event_ledger_.last_sequence())
    fail("event_ledger_unverified");
  std::vector<IpcEnvelope> output;
  for (const auto& record : verified.records) {
    const auto& event = record.event;
    if (event.execution_session_id != configuration_.execution_session_id ||
        (event.strategy_id && *event.strategy_id != configuration_.expected_strategy_id))
      fail("event_ledger_scope_invalid");
    if (!event.intent_id || *event.intent_id != intent_id) continue;
    output.push_back({IpcMessageKind::ExecutionEvent, configuration_.execution_session_id,
                      configuration_.expected_strategy_id, std::nullopt, record.sequence,
                      event.to_json(),
                      std::nullopt});
  }
  return output;
}
std::vector<ReplayEvent> Executor::reconnect(std::uint64_t after_event_sequence,
                                             std::string_view session,
                                             std::string_view strategy) const {
  if (session != configuration_.execution_session_id ||
      strategy != configuration_.expected_strategy_id)
    fail("replay_scope_invalid");
  const auto verified = durable_event_ledger_.verify(LedgerVerificationMode::RetainRecords);
  if (!verified.clean() || verified.verified_records != durable_event_ledger_.last_sequence() ||
      after_event_sequence > verified.verified_records)
    fail("event_ledger_unverified");
  std::vector<ReplayEvent> output;
  for (const auto& record : verified.records) {
    if (record.sequence <= after_event_sequence) continue;
    if (record.event.execution_session_id != session ||
        (record.event.strategy_id && *record.event.strategy_id != strategy))
      fail("event_ledger_scope_invalid");
    output.push_back({record.sequence, std::string(session), std::string(strategy),
                      record.event.to_json()});
  }
  return output;
}
void Executor::establish_acknowledgement_cursor(std::uint64_t event_sequence) {
  const std::lock_guard<std::mutex> guard(state_mutex_);
  if (event_sequence < last_acknowledged_event_sequence_ ||
      event_sequence > durable_event_ledger_.last_sequence())
    fail("ipc_ack_sequence_invalid");
  last_acknowledged_event_sequence_ = event_sequence;
  last_delivered_event_sequence_ = std::max(last_delivered_event_sequence_, event_sequence);
  auto& queue = queues_[static_cast<std::size_t>(ExecutorQueueKind::OutboundEvent)];
  while (queue.discard_front_if([&](const ExecutorStageMessage& message) {
    const auto* item = std::get_if<IpcEnvelope>(&message);
    return item && item->event_sequence && *item->event_sequence <= event_sequence;
  })) {}
}
void Executor::acknowledge_events_through(std::uint64_t event_sequence) {
  const std::lock_guard<std::mutex> guard(state_mutex_);
  if (event_sequence < last_acknowledged_event_sequence_ ||
      event_sequence > last_delivered_event_sequence_)
    fail("ipc_ack_sequence_invalid");
  last_acknowledged_event_sequence_ = event_sequence;
  auto& queue = queues_[static_cast<std::size_t>(ExecutorQueueKind::OutboundEvent)];
  while (queue.discard_front_if([&](const ExecutorStageMessage& message) {
    const auto* item = std::get_if<IpcEnvelope>(&message);
    return item && item->event_sequence && *item->event_sequence <= event_sequence;
  })) {}
  update_shutdown_success_locked();
}
void Executor::mark_event_delivered(std::uint64_t event_sequence) {
  const std::lock_guard<std::mutex> guard(state_mutex_);
  if (event_sequence == 0U || event_sequence > durable_event_ledger_.last_sequence())
    fail("ipc_event_delivery_sequence_invalid");
  last_delivered_event_sequence_ = std::max(last_delivered_event_sequence_, event_sequence);
}
void Executor::request_stop() noexcept {
  const std::lock_guard<std::mutex> guard(state_mutex_);
  if (!stop_requested_.exchange(true)) {
    shutdown_deadline_ = std::chrono::steady_clock::now() +
        std::chrono::milliseconds(configuration_.shutdown_deadline_ms);
  }
}
std::chrono::steady_clock::time_point Executor::shutdown_deadline() const noexcept {
  const std::lock_guard<std::mutex> guard(state_mutex_);
  return shutdown_deadline_.value_or(std::chrono::steady_clock::time_point::min());
}
std::uint64_t Executor::last_delivered_event_sequence() const noexcept {
  const std::lock_guard<std::mutex> guard(state_mutex_);
  return last_delivered_event_sequence_;
}
void Executor::update_shutdown_success_locked() noexcept {
  if (!shutdown_result_ || !shutdown_core_succeeded_ || !shutdown_deadline_ ||
      std::chrono::steady_clock::now() >= *shutdown_deadline_) {
    shutdown_succeeded_ = false;
    return;
  }
  const bool queues_drained = std::all_of(
      queues_.begin(), queues_.end(), [](const auto& queue) {
        return queue.metrics().depth == 0U;
      });
  shutdown_succeeded_ = queues_drained && reserved_broker_updates_ == 0U &&
      last_acknowledged_event_sequence_ >= durable_event_ledger_.last_sequence();
}
bool Executor::enqueue(ExecutorQueueKind queue, IpcEnvelope envelope, bool broker_attempted) {
  const auto index = static_cast<std::size_t>(queue);
  if (index >= queues_.size() || !queues_[index].try_push(std::move(envelope))) {
    stop_once(queue_reason(queue, broker_attempted)); return false;
  }
  return true;
}
void Executor::stop_once(std::string reason) {
  if (!safety_reason_) { safety_reason_ = std::move(reason); session_.activate_kill_switch(*safety_reason_); }
}
bool Executor::ready() const noexcept {
  const std::lock_guard<std::mutex> guard(state_mutex_);
  if (!last_observation_receive_ns_ || !last_observation_activity_) return false;
  const auto now = clock_.now_ns();
  if (now < *last_observation_receive_ns_) return false;
  const auto wall_age = now - *last_observation_receive_ns_;
  const auto inactive = std::chrono::steady_clock::now() - *last_observation_activity_;
  return market_authenticated_ && strategy_authenticated_ && fresh_observation_ &&
         wall_age >= 0 && wall_age <= configuration_.required_initial_observation_freshness_ns &&
         inactive <= std::chrono::nanoseconds(
                         configuration_.required_initial_observation_freshness_ns) &&
         session_.ready() && !safety_reason_ && !stop_requested_.load();
}
bool Executor::check_market_freshness() {
  const std::lock_guard<std::mutex> guard(state_mutex_);
  if (!last_observation_receive_ns_ || !last_observation_activity_) return false;
  const auto now = clock_.now_ns();
  if (now < *last_observation_receive_ns_) {
    stop_once("market_observation_stale");
    fresh_observation_ = false;
    return false;
  }
  const auto age = now - *last_observation_receive_ns_;
  const auto inactive = std::chrono::steady_clock::now() - *last_observation_activity_;
  if (age > configuration_.required_initial_observation_freshness_ns ||
      inactive > std::chrono::nanoseconds(configuration_.required_initial_observation_freshness_ns)) {
    stop_once("market_observation_stale");
    fresh_observation_ = false;
    return false;
  }
  return true;
}
bool Executor::next_market_is_safety_fault() const {
  return queues_[static_cast<std::size_t>(ExecutorQueueKind::MarketReceive)]
      .front_satisfies([&](const ExecutorStageMessage& message) {
        const auto* envelope = std::get_if<IpcEnvelope>(&message);
        if (!envelope) return true;
        try {
          const auto book = StrategyBookObservation::parse(envelope->canonical_payload);
          const auto now = clock_.now_ns();
          return unusable_book(book) || now < book.receive_timestamp_ns ||
                 now - book.receive_timestamp_ns >
                     configuration_.required_initial_observation_freshness_ns;
        } catch (...) {
          return true;
        }
      });
}
SessionStopResult Executor::shutdown() {
  request_stop();
  if (durable_event_ledger_.last_sequence() > event_sequence_)
    static_cast<void>(collect_events_after(event_sequence_, false));
  std::optional<std::uint64_t> shutdown_safety_before;
  {
    const std::lock_guard<std::mutex> guard(state_mutex_);
    if (shutdown_result_) return *shutdown_result_;
    if (!safety_reason_) {
      shutdown_safety_before = durable_event_ledger_.last_sequence();
      safety_reason_ = "executor_shutdown";
      session_.activate_kill_switch(*safety_reason_);
    }
  }
  if (shutdown_safety_before)
    static_cast<void>(collect_events_after(*shutdown_safety_before, false));
  const auto deadline = shutdown_deadline();
  const auto before_deadline = [&] { return std::chrono::steady_clock::now() < deadline; };
  while (before_deadline() && queue_metrics(ExecutorQueueKind::RiskWork).depth != 0U)
    static_cast<void>(process_next_risk_work());
  while (before_deadline() &&
         queue_metrics(ExecutorQueueKind::StrategyReceive).depth != 0U) {
    static_cast<void>(process_next_intent());
    while (before_deadline() && queue_metrics(ExecutorQueueKind::RiskWork).depth != 0U)
      static_cast<void>(process_next_risk_work());
  }
  while (before_deadline() && queue_metrics(ExecutorQueueKind::RiskWork).depth != 0U)
    static_cast<void>(process_next_risk_work());
  while (before_deadline() && queue_metrics(ExecutorQueueKind::BrokerSubmission).depth != 0U)
    static_cast<void>(process_next_broker_submission());
  auto& broker_updates = queues_[static_cast<std::size_t>(ExecutorQueueKind::BrokerUpdate)];
  while (before_deadline()) {
    auto update_message = broker_updates.try_pop();
    if (!update_message) break;
    if (auto* update = std::get_if<BrokerUpdateEnvelope>(&*update_message))
      static_cast<void>(session_.accept_broker_update(*update));
  }
  release_broker_update_reservations();
  auto& market_receive = queues_[static_cast<std::size_t>(ExecutorQueueKind::MarketReceive)];
  while (before_deadline() && market_receive.try_pop()) {
    const auto ledger_before = durable_event_ledger_.last_sequence();
    session_.activate_kill_switch("shutdown_market_receive_refused");
    static_cast<void>(collect_events_after(ledger_before, false));
  }
  while (before_deadline() &&
         queue_metrics(ExecutorQueueKind::LedgerCommand).depth != 0U)
    std::this_thread::yield();
  SessionStopResult stopped;
  if (before_deadline()) {
    const auto ledger_before = durable_event_ledger_.last_sequence();
    stopped = session_.stop(deadline);
    static_cast<void>(collect_events_after(ledger_before, !stopped.cancel_results.empty()));
  }
  {
    const std::lock_guard<std::mutex> guard(state_mutex_);
    shutdown_result_ = std::move(stopped);
  }
  const bool cancels_factual = std::all_of(
      shutdown_result_->cancel_results.begin(), shutdown_result_->cancel_results.end(),
      [](const BrokerMutationResult& result) {
        return result.status == BrokerMutationStatus::Acknowledged &&
               result.terminal_state_confirmed;
      });
  {
    const std::lock_guard<std::mutex> guard(state_mutex_);
    shutdown_core_succeeded_ = before_deadline() &&
        shutdown_result_->cancellation_complete && shutdown_result_->reconciliation_exact &&
        shutdown_result_->ledger_flushed && shutdown_result_->stopped_recorded &&
        cancels_factual;
    update_shutdown_success_locked();
  }
  return *shutdown_result_;
}
QueueMetrics Executor::queue_metrics(ExecutorQueueKind queue) const {
  const auto index = static_cast<std::size_t>(queue);
  if (index >= queues_.size()) throw std::out_of_range("queue_kind_invalid");
  return queues_[index].metrics();
}

ExecutorServer::ExecutorServer(Executor& executor, ExecutorConfiguration configuration,
                               ExpectedPeerIdentity market_identity,
                               ExpectedPeerIdentity strategy_identity,
                               const PeerInspector& market_inspector,
                               const PeerInspector& strategy_inspector,
                               bool production_peer_validation)
    : executor_(executor), configuration_(std::move(configuration)),
      market_identity_(std::move(market_identity)), strategy_identity_(std::move(strategy_identity)),
      market_inspector_(market_inspector), strategy_inspector_(strategy_inspector),
      production_peer_validation_(production_peer_validation),
#if defined(__APPLE__)
      mode_(IpcSocketMode::Stream),
#else
      mode_(IpcSocketMode::SeqPacket),
#endif
      codec_(configuration_.maximum_packet_bytes),
      market_listener_(ProtectedUnixListener::create(configuration_.runtime_directory,
                                                     configuration_.market_socket_basename, mode_)),
      strategy_listener_(ProtectedUnixListener::create(configuration_.runtime_directory,
                                                       configuration_.strategy_socket_basename, mode_)) {
  if (market_identity_.role != PeerRole::MarketPublisher ||
      strategy_identity_.role != PeerRole::StrategyClient) fail("peer_policy_invalid");
}

int ExecutorServer::accept_authenticated(ProtectedUnixListener& listener, PeerRole role,
                                         const ExpectedPeerIdentity& expected,
                                         const PeerInspector& inspector,
                                         std::optional<std::uint64_t>& replay_cursor,
                                         bool reconnect) {
  const auto reconnect_deadline = std::chrono::steady_clock::now() +
      std::chrono::milliseconds(configuration_.reconnect_window_ms);
  std::size_t failed_attempts = 0U;
  static constexpr std::size_t maximum_failed_attempts = 8U;
  while (!executor_.stop_requested()) {
    if (std::chrono::steady_clock::now() >= reconnect_deadline)
      fail(reconnect ? "ipc_reconnect_window_expired" : "ipc_authentication_window_expired");
    int descriptor = -1;
    try { descriptor = listener.accept_one_until(reconnect_deadline); }
    catch (const IpcError& error) {
      if (error.code() == "ipc_timeout") continue;
      throw;
    }
    try {
      ++nonce_sequence_;
      const auto nonce = fresh_nonce(configuration_.execution_session_id, nonce_sequence_);
      const auto challenge = canonical_json(JsonValue(JsonObject{
          {"nonce", json_text(nonce)}, {"schema_version", json_text("1.0.0")}}));
      write_ipc_frame_until(descriptor, mode_, codec_, challenge, reconnect_deadline);
      const auto handshake = parse_ipc_handshake(
          read_ipc_frame_until(descriptor, mode_, codec_, reconnect_deadline));
      if (!constant_time_equal(handshake.bindings.nonce, nonce) || handshake.bindings.role != role)
        fail("ipc_nonce_or_role_invalid");
      executor_.authenticate_peer(expected, handshake, inspector, descriptor,
                                  production_peer_validation_);
      if (std::chrono::steady_clock::now() >= reconnect_deadline)
        fail(reconnect ? "ipc_reconnect_window_expired" : "ipc_authentication_window_expired");
      replay_cursor = handshake.after_event_sequence;
      return descriptor;
    } catch (...) {
      (void)::close(descriptor);
      ++failed_attempts;
      if (failed_attempts >= maximum_failed_attempts)
        fail("ipc_authentication_attempts_exhausted");
    }
  }
  return -1;
}

void ExecutorServer::run() {
  struct Finalize {
    Executor& executor;
    ProtectedUnixListener& market;
    ProtectedUnixListener& strategy;
    ~Finalize() {
      try { (void)executor.shutdown(); } catch (...) {}
      market.close(); strategy.close();
    }
  } finalize{executor_, market_listener_, strategy_listener_};
  struct Descriptor {
    int value{-1};
    ~Descriptor() { if (value >= 0) (void)::close(value); }
    void reset(int next = -1) { if (value >= 0) (void)::close(value); value = next; }
  } market, strategy;
  std::optional<std::uint64_t> ignored_cursor, strategy_cursor;
  market.reset(accept_authenticated(market_listener_, PeerRole::MarketPublisher,
                                    market_identity_, market_inspector_, ignored_cursor));
  if (market.value < 0) return;
  strategy.reset(accept_authenticated(strategy_listener_, PeerRole::StrategyClient,
                                      strategy_identity_, strategy_inspector_, strategy_cursor));
  if (strategy.value < 0) return;
  const auto deadline = std::chrono::milliseconds(configuration_.io_deadline_ms);
  bool strategy_delivery_failed = false;
  const auto send_event = [&](int descriptor, const IpcEnvelope& event) {
    if (!event.event_sequence) fail("ipc_event_sequence_invalid");
    try {
      write_ipc_frame(descriptor, mode_, codec_, encode_ipc_envelope(event), deadline);
      executor_.mark_event_delivered(*event.event_sequence);
      return true;
    } catch (const IpcError&) {
      strategy_delivery_failed = true;
      (void)::shutdown(descriptor, SHUT_RDWR);
      return false;
    }
  };
  const auto send_events = [&](const std::vector<IpcEnvelope>& events) {
    for (const auto& event : events)
      if (!send_event(strategy.value, event)) return false;
    return true;
  };
  const auto send_market_result = [&](const MarketAcceptResult& accepted) {
    for (const auto& event : accepted.execution_events) {
      if (ExecutionEvent::parse(event.canonical_payload).event_type == "session_started")
        continue;
      if (!send_event(strategy.value, event)) return false;
    }
    if (accepted.strategy_book) {
      try {
        write_ipc_frame(strategy.value, mode_, codec_,
                        encode_ipc_envelope(*accepted.strategy_book), deadline);
      } catch (const IpcError&) {
        strategy_delivery_failed = true;
        (void)::shutdown(strategy.value, SHUT_RDWR);
        return false;
      }
    }
    for (const auto& event : accepted.execution_events) {
      if (ExecutionEvent::parse(event.canonical_payload).event_type != "session_started")
        continue;
      if (!send_event(strategy.value, event)) return false;
    }
    return true;
  };
  {
    const auto cursor = strategy_cursor.value_or(0U);
    executor_.establish_acknowledgement_cursor(cursor);
    for (const auto& item : executor_.reconnect(cursor, configuration_.execution_session_id,
                                                configuration_.expected_strategy_id)) {
      const IpcEnvelope event{IpcMessageKind::ExecutionEvent, item.execution_session_id,
                              item.strategy_id, std::nullopt, item.sequence,
                              item.canonical_event, std::nullopt};
      if (!send_event(strategy.value, event)) break;
    }
  }
  struct ReaderResult {
    PeerRole role{PeerRole::MarketPublisher};
    bool timed_out{};
    bool overflow{};
    std::optional<IpcEnvelope> control;
    std::exception_ptr error;
  };
  const auto read_market = [&]() {
    return std::async(std::launch::async, [&]() -> ReaderResult {
      try {
        executor_.validate_peer_connection(PeerRole::MarketPublisher, market_inspector_,
                                           market.value);
        auto envelope = parse_ipc_envelope(read_ipc_frame(market.value, mode_, codec_, deadline));
        return {PeerRole::MarketPublisher, false,
                !executor_.submit_market_from_reader(std::move(envelope)), std::nullopt, nullptr};
      } catch (const IpcError& error) {
        if (error.code() == "ipc_timeout")
          return {PeerRole::MarketPublisher, true, false, std::nullopt, nullptr};
        return {PeerRole::MarketPublisher, false, false, std::nullopt,
                std::current_exception()};
      } catch (...) {
        return {PeerRole::MarketPublisher, false, false, std::nullopt,
                std::current_exception()};
      }
    });
  };
  const auto read_strategy = [&]() {
    return std::async(std::launch::async, [&]() -> ReaderResult {
      try {
        executor_.validate_peer_connection(PeerRole::StrategyClient, strategy_inspector_,
                                           strategy.value);
        auto envelope = parse_ipc_envelope(read_ipc_frame(strategy.value, mode_, codec_, deadline));
        authorize_inbound(PeerRole::StrategyClient, envelope,
                          configuration_.execution_session_id, configuration_.expected_strategy_id);
        if (envelope.kind == IpcMessageKind::OrderIntent)
          return {PeerRole::StrategyClient, false,
                  !executor_.submit_intent_from_reader(std::move(envelope)), std::nullopt, nullptr};
        return {PeerRole::StrategyClient, false, false, std::move(envelope), nullptr};
      } catch (const IpcError& error) {
        if (error.code() == "ipc_timeout")
          return {PeerRole::StrategyClient, true, false, std::nullopt, nullptr};
        return {PeerRole::StrategyClient, false, false, std::nullopt,
                std::current_exception()};
      } catch (...) {
        return {PeerRole::StrategyClient, false, false, std::nullopt,
                std::current_exception()};
      }
    });
  };
  std::optional<std::future<ReaderResult>> market_reader;
  std::optional<std::future<ReaderResult>> strategy_reader;
  while (!executor_.stop_requested()) {
    const auto depth = [&](ExecutorQueueKind queue) {
      return executor_.queue_metrics(queue).depth;
    };
    const bool staged_work = depth(ExecutorQueueKind::MarketReceive) != 0U ||
                             depth(ExecutorQueueKind::StrategyReceive) != 0U ||
                             depth(ExecutorQueueKind::RiskWork) != 0U ||
                             depth(ExecutorQueueKind::BrokerSubmission) != 0U;
    if (!market_reader && !strategy_reader && staged_work) {
      if (depth(ExecutorQueueKind::MarketReceive) != 0U &&
          executor_.next_market_is_safety_fault()) {
        auto rejected_market = executor_.process_next_market();
        if (!strategy_delivery_failed) (void)send_market_result(rejected_market);
      } else if (!strategy_delivery_failed &&
                 depth(ExecutorQueueKind::BrokerSubmission) != 0U) {
        (void)send_events(executor_.process_next_broker_submission());
      } else if (!strategy_delivery_failed && depth(ExecutorQueueKind::RiskWork) != 0U) {
        (void)send_events(executor_.process_next_risk_work());
      } else if (!strategy_delivery_failed &&
                 depth(ExecutorQueueKind::StrategyReceive) != 0U) {
        (void)send_events(executor_.process_next_intent());
      } else if (!strategy_delivery_failed &&
                 depth(ExecutorQueueKind::MarketReceive) != 0U) {
        (void)send_market_result(executor_.process_next_market());
      }
      continue;
    }
    if (!market_reader) market_reader.emplace(read_market());
    if (!strategy_reader) strategy_reader.emplace(read_strategy());
    const bool strategy_ready =
        strategy_reader->wait_for(std::chrono::milliseconds(0)) == std::future_status::ready;
    const bool market_ready =
        market_reader->wait_for(std::chrono::milliseconds(0)) == std::future_status::ready;
    if (!strategy_ready || !market_ready) {
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
      (void)executor_.check_market_freshness();
      continue;
    }
    auto market_result = market_reader->get();
    market_reader.reset();
    auto strategy_result = strategy_reader->get();
    strategy_reader.reset();
    if (market_result.error) {
        executor_.record_peer_disconnect(PeerRole::MarketPublisher);
        std::rethrow_exception(market_result.error);
    }
    if (market_result.overflow) {
        executor_.record_reader_overflow(ExecutorQueueKind::MarketReceive);
    } else if (!market_result.timed_out) {
        // The reader already transferred the immutable envelope into MarketReceive.
    }
    if (strategy_result.error) {
      executor_.record_peer_disconnect(PeerRole::StrategyClient);
      strategy.reset(); strategy_cursor.reset();
      strategy.reset(accept_authenticated(strategy_listener_, PeerRole::StrategyClient,
                                          strategy_identity_, strategy_inspector_, strategy_cursor,
                                          true));
      if (strategy.value < 0) break;
      strategy_delivery_failed = false;
      const auto cursor = strategy_cursor.value_or(0U);
      executor_.establish_acknowledgement_cursor(cursor);
      (void)executor_.restore_strategy_authority_after_reconnect();
      for (const auto& item : executor_.reconnect(cursor, configuration_.execution_session_id,
                                                  configuration_.expected_strategy_id)) {
        const IpcEnvelope event{IpcMessageKind::ExecutionEvent, item.execution_session_id,
                                item.strategy_id, std::nullopt, item.sequence,
                                item.canonical_event, std::nullopt};
        if (!send_event(strategy.value, event)) break;
      }
    } else if (strategy_result.overflow) {
      executor_.record_reader_overflow(ExecutorQueueKind::StrategyReceive);
    } else if (strategy_result.control && strategy_result.control->event_sequence) {
      const auto acknowledgement =
          EventAcknowledgement::parse(strategy_result.control->canonical_payload);
      executor_.acknowledge_events_through(acknowledgement.acknowledged_event_sequence);
    } else if (!strategy_result.timed_out) {
      // The reader already transferred the immutable envelope into StrategyReceive.
    }
  }
  const auto consume_final_reader = [&](std::optional<std::future<ReaderResult>>& reader) {
    if (!reader) return;
    auto result = reader->get();
    reader.reset();
    if (result.role == PeerRole::StrategyClient && result.control &&
        result.control->event_sequence) {
      const auto acknowledgement =
          EventAcknowledgement::parse(result.control->canonical_payload);
      executor_.acknowledge_events_through(acknowledgement.acknowledged_event_sequence);
    }
  };
  consume_final_reader(market_reader);
  consume_final_reader(strategy_reader);
  static_cast<void>(executor_.shutdown());
  const auto final_deadline = executor_.shutdown_deadline();
  if (strategy.value < 0 || std::chrono::steady_clock::now() >= final_deadline) return;
  try {
    const auto final_events = executor_.reconnect(
        executor_.last_delivered_event_sequence(), configuration_.execution_session_id,
        configuration_.expected_strategy_id);
    for (const auto& item : final_events) {
      const IpcEnvelope event{IpcMessageKind::ExecutionEvent, item.execution_session_id,
                              item.strategy_id, std::nullopt, item.sequence,
                              item.canonical_event, std::nullopt};
      write_ipc_frame_until(strategy.value, mode_, codec_, encode_ipc_envelope(event),
                            final_deadline);
      executor_.mark_event_delivered(item.sequence);
    }
    while (!executor_.shutdown_succeeded() &&
           std::chrono::steady_clock::now() < final_deadline) {
      auto acknowledgement_envelope = parse_ipc_envelope(
          read_ipc_frame_until(strategy.value, mode_, codec_, final_deadline));
      authorize_inbound(PeerRole::StrategyClient, acknowledgement_envelope,
                        configuration_.execution_session_id,
                        configuration_.expected_strategy_id);
      if (acknowledgement_envelope.kind != IpcMessageKind::EventAcknowledgement ||
          !acknowledgement_envelope.event_sequence)
        fail("ipc_shutdown_ack_required");
      const auto acknowledgement =
          EventAcknowledgement::parse(acknowledgement_envelope.canonical_payload);
      executor_.acknowledge_events_through(acknowledgement.acknowledged_event_sequence);
    }
  } catch (const IpcError&) {
    return;
  }
}

int executor_cli(const std::vector<std::string>& arguments, std::ostream& output,
                 std::ostream& error) {
  try {
    if (arguments.size() == 1U && arguments[0] == "version") {
      if (!lowercase_hex(kSourceRevision, 40U)) fail("executor_source_revision_unattested");
      if ((std::string_view(kSourceState) != "clean" &&
           std::string_view(kSourceState) != "dirty") ||
          !lowercase_hex(kSourceTreeDigest, 64U))
        fail("executor_source_tree_unattested");
      output << "shaurya-executor " << kProjectVersion
             << " mode=shadow kotak_live=off commit=" << kSourceRevision
             << " source_state=" << kSourceState
             << " source_tree_sha256=" << kSourceTreeDigest
             << " build_sha256=" << running_executable_digest() << '\n';
      return 0;
    }
    if (arguments.empty()) { error << "[EXECUTOR_REFUSED] code=command_required\n"; return 2; }
    const std::string command = arguments[0];
    const std::vector<std::string> options(arguments.begin() + 1, arguments.end());
    if (command == "validate-config") {
      const auto path = exact_option(options, "--config"); if (!path) fail("cli_options_invalid");
      const auto config = load_executor_configuration(*path); (void)config;
      output << "[EXECUTOR_CONFIG_OK] mode=shadow\n"; return 0;
    }
    if (command == "verify-ledger") {
      const auto path = exact_option(options, "--ledger"); if (!path) fail("cli_options_invalid");
      const auto verified = verify_ledger(*path);
      if (!verified.clean()) fail("ledger_verification_failed");
      output << "[EXECUTOR_LEDGER_OK] records=" << verified.verified_records << '\n'; return 0;
    }
    if (command == "replay") {
      if (options.size() != 4U || options[0] != "--config" || options[2] != "--ledger")
        fail("cli_options_invalid");
      const std::filesystem::path config_path(options[1]), ledger_path(options[3]);
      if (!config_path.is_absolute() || config_path.lexically_normal() != config_path ||
          !ledger_path.is_absolute() || ledger_path.lexically_normal() != ledger_path)
        fail("cli_options_invalid");
      const auto config = load_executor_configuration(config_path);
      if (ledger_path != config.ledger_path) fail("ledger_path_mismatch");
      const auto verified = verify_ledger(ledger_path); if (!verified.clean()) fail("ledger_verification_failed");
      output << "[EXECUTOR_REPLAY_OK] records=" << verified.verified_records << '\n'; return 0;
    }
    if (command == "serve") {
      if (options.size() != 4U || options[0] != "--config" || options[2] != "--launch-attestation")
        fail("cli_options_invalid");
      const std::filesystem::path config_path(options[1]), attestation_path(options[3]);
      if (!config_path.is_absolute() || config_path.lexically_normal() != config_path ||
          !attestation_path.is_absolute() || attestation_path.lexically_normal() != attestation_path)
        fail("cli_options_invalid");
      const auto config = load_executor_configuration(config_path);
      if (!constant_time_equal(config.expected_executor_build_digest,
                               running_executable_digest()))
        fail("executor_build_digest_mismatch");
      RuntimeClock clock;
      const auto launch_evidence =
          validate_launch_attestation(config, attestation_path, clock.now_ns());
      std::optional<ExecutionLedgerSessionAdapter> audit;
      struct stat ledger_metadata{};
      const auto ledger_basename = config.ledger_path.filename().string();
      if (::fstatat(*config.protected_artifact_descriptor, ledger_basename.c_str(),
                    &ledger_metadata, AT_SYMLINK_NOFOLLOW) == 0) {
        audit.emplace(ExecutionLedgerSessionAdapter::open_existing_at(
            *config.protected_artifact_descriptor, ledger_basename));
      } else if (errno == ENOENT) {
        audit.emplace(ExecutionLedgerSessionAdapter::create_new_at(
            *config.protected_artifact_descriptor, ledger_basename));
      } else {
        fail("event_ledger_unverifiable");
      }
      const auto ledger_verification = audit->ledger().verify(
          LedgerVerificationMode::RetainRecords);
      reject_replayed_launch_attestation(ledger_verification, launch_evidence);
      const auto recovered_paper = recover_paper_broker(ledger_verification);
      std::int64_t routing_timestamp_ns = 0;
      const auto routing_snapshot_bytes = read_protected_beneath(
          config, config.routing_snapshot, kMaximumJsonBytes, &routing_timestamp_ns);
      const auto routing_manifest_bytes = read_protected_beneath(
          config, config.routing_manifest, kMaximumJsonBytes);
      auto resolver_value = InstrumentResolver::load_documents(
          routing_snapshot_bytes, config.routing_snapshot.filename().string(),
          routing_manifest_bytes, config.trading_date);
      RuntimeResolver resolver(std::move(resolver_value), config.trading_date,
                               routing_timestamp_ns);
      RiskConfiguration risk_configuration;
      try {
        risk_configuration = RiskConfiguration::parse(read_protected_beneath(
            config, config.risk_configuration_path, 64U * 1024U));
      } catch (const std::exception&) { fail("risk_configuration_invalid"); }
      if (risk_configuration.trading_date != config.trading_date)
        fail("risk_trading_date_mismatch");
      validate_paper_model_bytes(read_protected_beneath(
          config, config.paper_model_path, 16U * 1024U));
      PaperBroker broker(recovered_paper.snapshot, false);
      ExecutionSession session(config.execution_session_id,
                               RiskEngine(std::move(risk_configuration)), recovered_paper.replayed,
                               *audit, resolver, broker, clock, 1024U, launch_evidence);
      if (!session.preflight()) fail("startup_reconciliation_failed");
      Executor executor(config, session, audit->ledger(), clock);
      SystemPeerInspector inspector;
      ExecutorServer server(executor, config, config.market_peer_identity,
                            config.strategy_peer_identity, inspector, inspector, true);
      runtime_stop_requested = 0;
      const auto old_interrupt = std::signal(SIGINT, runtime_signal_handler);
      const auto old_terminate = std::signal(SIGTERM, runtime_signal_handler);
      std::exception_ptr worker_error;
      std::atomic<bool> worker_done{};
      std::thread worker([&] {
        try { server.run(); } catch (...) { worker_error = std::current_exception(); }
        worker_done.store(true);
      });
      output << "[EXECUTOR_SHADOW_LISTENING] transport=unix-local-only\n";
      output.flush();
      while (runtime_stop_requested == 0 && !worker_done.load())
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
      server.request_stop();
      worker.join();
      (void)std::signal(SIGINT, old_interrupt); (void)std::signal(SIGTERM, old_terminate);
      if (worker_error) std::rethrow_exception(worker_error);
      if (!executor.shutdown_succeeded()) {
        error << "[EXECUTOR_SHADOW_STOP_FAILED] state=unconfirmed\n";
        return 2;
      }
      output << "[EXECUTOR_SHADOW_STOPPED] state=factual\n";
      return 0;
    }
    fail("command_unknown");
  } catch (const std::exception& exception) {
    error << "[EXECUTOR_REFUSED] code=" << exception.what() << '\n'; return 2;
  }
}

}  // namespace shaurya::execution
