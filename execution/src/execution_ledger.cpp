#include "shaurya/execution/execution_ledger.hpp"

#include "shaurya/execution/canonical_json.hpp"

#include <cerrno>
#include <fcntl.h>
#include <set>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

namespace shaurya::execution {
namespace {
constexpr std::uint64_t kMaximumLedgerBytes = 64U * 1024U * 1024U;
constexpr std::string_view kGenesisHash =
    "0000000000000000000000000000000000000000000000000000000000000000";

JsonValue text(std::string value) { return JsonValue(std::move(value)); }
JsonValue integer(std::uint64_t value) { return JsonValue(JsonInteger{std::to_string(value)}); }
JsonValue integer(std::int64_t value) { return JsonValue(JsonInteger{std::to_string(value)}); }
void optional(JsonObject& object, std::string key, const std::optional<std::string>& value) {
  if (value) object.emplace(std::move(key), text(*value));
}
const JsonValue& required(const JsonObject& object, std::string_view field) {
  const auto found = object.find(field);
  if (found == object.end()) throw LedgerError("ledger_missing_field");
  return found->second;
}
std::optional<std::string> optional_string(const JsonObject& object, std::string_view field) {
  const auto found = object.find(field);
  if (found == object.end()) return std::nullopt;
  return json_string(found->second, field);
}
JsonObject record_without_hash(const LedgerRecord& record) {
  JsonObject object;
  object.emplace("schema_version", text(std::string(kContractVersion)));
  object.emplace("sequence", integer(record.sequence));
  object.emplace("event_id", text(record.event.event_id));
  object.emplace("event_type", text(record.event.event_type));
  object.emplace("timestamp_ns", integer(record.event.timestamp_ns));
  object.emplace("execution_session_id", text(record.event.execution_session_id));
  optional(object, "strategy_id", record.event.strategy_id);
  optional(object, "strategy_run_id", record.event.strategy_run_id);
  optional(object, "intent_id", record.event.intent_id);
  optional(object, "internal_order_id", record.event.internal_order_id);
  object.emplace("payload", JsonValue(record.event.payload));
  object.emplace("previous_record_hash", text(record.previous_record_hash));
  return object;
}
bool digest(std::string_view value) {
  if (value.size() != 64) return false;
  for (const char item : value) {
    if (!((item >= '0' && item <= '9') || (item >= 'a' && item <= 'f'))) return false;
  }
  return true;
}
bool plausible_record_prefix(std::string_view value) {
  constexpr std::string_view beginning = "{\"event_id\"";
  return value.size() <= beginning.size() ? beginning.starts_with(value)
                                          : value.starts_with(beginning);
}
LedgerRecord parse_record(std::string_view line) {
  if (line.empty() || line.size() > kMaximumLedgerRecordBytes) {
    throw LedgerError("ledger_record_size");
  }
  const auto document = parse_json(line, kMaximumLedgerRecordBytes);
  const auto& object = json_object(document, "ledger_record");
  static const std::set<std::string, std::less<>> required_fields{
      "schema_version", "sequence", "event_id", "event_type", "timestamp_ns",
      "execution_session_id", "payload", "previous_record_hash", "record_hash"};
  static const std::set<std::string, std::less<>> optional_fields{
      "strategy_id", "strategy_run_id", "intent_id", "internal_order_id"};
  for (const auto& field : required_fields) {
    if (!object.contains(field)) throw LedgerError("ledger_missing_field");
  }
  for (const auto& [field, unused] : object) {
    static_cast<void>(unused);
    if (!required_fields.contains(field) && !optional_fields.contains(field)) {
      throw LedgerError("ledger_unknown_field");
    }
  }
  if (json_string(required(object, "schema_version"), "schema_version") != kContractVersion) {
    throw LedgerError("ledger_unsupported_version");
  }
  JsonObject event_object;
  event_object.emplace("schema_version", text(std::string(kContractVersion)));
  for (const auto field : {"event_id", "event_type", "execution_session_id"}) {
    event_object.emplace(field, text(json_string(required(object, field), field)));
  }
  event_object.emplace("timestamp_ns",
                       integer(json_int64(required(object, "timestamp_ns"), "timestamp_ns")));
  event_object.emplace("payload", JsonValue(json_object(required(object, "payload"), "payload")));
  for (const auto field : {"strategy_id", "strategy_run_id", "intent_id", "internal_order_id"}) {
    if (const auto value = optional_string(object, field)) event_object.emplace(field, text(*value));
  }
  LedgerRecord record;
  record.sequence = json_uint64(required(object, "sequence"), "sequence");
  record.event = ExecutionEvent::parse(canonical_json(JsonValue(std::move(event_object))));
  record.previous_record_hash =
      json_string(required(object, "previous_record_hash"), "previous_record_hash");
  record.record_hash = json_string(required(object, "record_hash"), "record_hash");
  if (record.sequence == 0 || !digest(record.previous_record_hash) || !digest(record.record_hash)) {
    throw LedgerError("ledger_invalid_record");
  }
  return record;
}

std::filesystem::path absolute_normalized(const std::filesystem::path& path) {
  std::error_code error;
  auto absolute = std::filesystem::absolute(path, error);
  if (error) throw LedgerError("ledger_invalid_path");
  return absolute.lexically_normal();
}
bool ancestors_have_no_symlink(const std::filesystem::path& path) {
  const auto absolute = absolute_normalized(path);
  auto current = absolute.root_path();
  for (const auto& component : absolute.parent_path().relative_path()) {
    current /= component;
    struct stat status {};
    if (::lstat(current.c_str(), &status) != 0 || S_ISLNK(status.st_mode) ||
        !S_ISDIR(status.st_mode)) return false;
  }
  return true;
}
bool safe_parent(const std::filesystem::path& path) {
  if (!ancestors_have_no_symlink(path)) return false;
  struct stat status {};
  const auto parent = absolute_normalized(path).parent_path();
  return !parent.empty() && ::lstat(parent.c_str(), &status) == 0 && S_ISDIR(status.st_mode) &&
         status.st_uid == ::geteuid() && (status.st_mode & 0077) == 0;
}
bool safe_file(const std::filesystem::path& path, struct stat* output = nullptr) {
  if (!ancestors_have_no_symlink(path)) return false;
  struct stat status {};
  if (::lstat(path.c_str(), &status) != 0 || !S_ISREG(status.st_mode) ||
      status.st_uid != ::geteuid() || (status.st_mode & 0077) != 0) return false;
  if (output != nullptr) *output = status;
  return true;
}
bool path_matches(const std::filesystem::path& path, std::uint64_t device, std::uint64_t inode,
                  int descriptor) {
  struct stat linked {}, opened {};
  return safe_file(path, &linked) && ::fstat(descriptor, &opened) == 0 &&
         static_cast<std::uint64_t>(linked.st_dev) == device &&
         static_cast<std::uint64_t>(linked.st_ino) == inode &&
         static_cast<std::uint64_t>(opened.st_dev) == device &&
         static_cast<std::uint64_t>(opened.st_ino) == inode && opened.st_nlink == 1;
}

LedgerVerificationResult result(LedgerVerificationStatus status, std::string code,
                                std::uint64_t count, std::uint64_t prefix,
                                std::string last_hash, std::vector<LedgerRecord> records = {}) {
  return {status, std::move(code), count, prefix, std::move(last_hash), std::move(records)};
}

LedgerVerificationResult scan(const std::filesystem::path& raw_path, LedgerVerificationMode mode,
                              const LedgerRecordVisitor& visitor) {
  std::filesystem::path path;
  try { path = absolute_normalized(raw_path); }
  catch (const LedgerError& error) {
    return result(LedgerVerificationStatus::Unsafe, error.code(), 0, 0,
                  std::string(kGenesisHash));
  }
  struct stat linked {};
  if (!safe_file(path, &linked)) {
    return result(LedgerVerificationStatus::Unsafe, "ledger_unsafe_file", 0, 0,
                  std::string(kGenesisHash));
  }
  const int descriptor = ::open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (descriptor < 0) {
    return result(LedgerVerificationStatus::Unsafe, "ledger_open_failed", 0, 0,
                  std::string(kGenesisHash));
  }
  struct Close { int descriptor; ~Close() { if (descriptor >= 0) ::close(descriptor); } } close{descriptor};
  struct stat opened {};
  if (::fstat(descriptor, &opened) != 0 || linked.st_dev != opened.st_dev ||
      linked.st_ino != opened.st_ino) {
    return result(LedgerVerificationStatus::Unsafe, "ledger_identity_changed", 0, 0,
                  std::string(kGenesisHash));
  }

  std::set<std::string> event_ids;
  std::vector<LedgerRecord> retained;
  std::string line;
  line.reserve(4096);
  std::string previous(kGenesisHash);
  std::uint64_t count{};
  std::uint64_t prefix{};
  std::uint64_t total{};
  char buffer[8192];
  for (;;) {
    const auto read_count = ::read(descriptor, buffer, sizeof(buffer));
    if (read_count < 0) {
      if (errno == EINTR) continue;
      return result(LedgerVerificationStatus::Unsafe, "ledger_read_failed", count, prefix,
                    previous, std::move(retained));
    }
    if (read_count == 0) break;
    total += static_cast<std::uint64_t>(read_count);
    if (total > kMaximumLedgerBytes) {
      return result(LedgerVerificationStatus::Unsafe, "ledger_segment_too_large", count, prefix,
                    previous, std::move(retained));
    }
    for (std::ptrdiff_t index = 0; index < read_count; ++index) {
      const char item = buffer[index];
      if (item != '\n') {
        if (line.size() >= kMaximumLedgerRecordBytes) {
          return result(LedgerVerificationStatus::Corrupt, "ledger_record_size", count, prefix,
                        previous, std::move(retained));
        }
        line.push_back(item);
        continue;
      }
      LedgerRecord record;
      try {
        record = parse_record(line);
        if (record.sequence != count + 1) throw LedgerError("ledger_sequence_mismatch");
        if (record.previous_record_hash != previous) throw LedgerError("ledger_chain_mismatch");
        if (!event_ids.insert(record.event.event_id).second) {
          throw LedgerError("ledger_duplicate_event_id");
        }
        const auto expected = sha256_hex(canonical_json(JsonValue(record_without_hash(record))));
        if (record.record_hash != expected) throw LedgerError("ledger_hash_mismatch");
        if (ledger_record_json(record) != line) throw LedgerError("ledger_noncanonical_record");
      } catch (const LedgerError& error) {
        return result(LedgerVerificationStatus::Corrupt, error.code(), count, prefix, previous,
                      std::move(retained));
      } catch (const JsonError& error) {
        return result(LedgerVerificationStatus::Corrupt, error.code(), count, prefix, previous,
                      std::move(retained));
      } catch (const std::exception&) {
        return result(LedgerVerificationStatus::Corrupt, "ledger_invalid_record", count, prefix,
                      previous, std::move(retained));
      }
      previous = record.record_hash;
      ++count;
      prefix += static_cast<std::uint64_t>(line.size()) + 1U;
      if (mode == LedgerVerificationMode::RetainRecords) retained.push_back(record);
      if (visitor) visitor(record);
      line.clear();
    }
  }
  if (!path_matches(path, static_cast<std::uint64_t>(opened.st_dev),
                    static_cast<std::uint64_t>(opened.st_ino), descriptor)) {
    return result(LedgerVerificationStatus::Unsafe, "ledger_identity_changed", count, prefix,
                  previous, std::move(retained));
  }
  if (!line.empty()) {
    if (!plausible_record_prefix(line)) {
      return result(LedgerVerificationStatus::Corrupt, "ledger_invalid_truncated_prefix", count,
                    prefix, previous, std::move(retained));
    }
    try {
      static_cast<void>(parse_json(line, kMaximumLedgerRecordBytes));
      return result(LedgerVerificationStatus::Corrupt, "ledger_missing_final_newline", count,
                    prefix, previous, std::move(retained));
    } catch (const JsonError& error) {
      if (!error.incomplete()) {
        return result(LedgerVerificationStatus::Corrupt, error.code(), count, prefix, previous,
                      std::move(retained));
      }
      return result(LedgerVerificationStatus::TruncatedTail, "ledger_truncated_tail", count,
                    prefix, previous, std::move(retained));
    }
  }
  return result(LedgerVerificationStatus::Clean, {}, count, prefix, previous,
                std::move(retained));
}

void injected(const LedgerFaultHook& hook, LedgerFaultPoint point,
              LedgerDurabilityBoundary boundary, std::uint64_t bytes) {
  if (!hook) return;
  try { hook(point); }
  catch (...) { throw LedgerError("ledger_injected_failure", boundary, bytes); }
}
void write_all(int descriptor, std::string_view bytes, std::uint64_t& written) {
  while (!bytes.empty()) {
    const auto count = ::write(descriptor, bytes.data(), bytes.size());
    if (count < 0) {
      if (errno == EINTR) continue;
      throw LedgerError("ledger_write_failed",
                        written == 0 ? LedgerDurabilityBoundary::NotWritten
                                     : LedgerDurabilityBoundary::Uncertain,
                        written);
    }
    if (count == 0) {
      throw LedgerError("ledger_write_failed",
                        written == 0 ? LedgerDurabilityBoundary::NotWritten
                                     : LedgerDurabilityBoundary::Uncertain,
                        written);
    }
    written += static_cast<std::uint64_t>(count);
    bytes.remove_prefix(static_cast<std::size_t>(count));
  }
}
}  // namespace

LedgerError::LedgerError(std::string code, LedgerDurabilityBoundary boundary,
                         std::uint64_t bytes_written)
    : std::runtime_error(code), code_(std::move(code)), boundary_(boundary),
      bytes_written_(bytes_written) {}
const std::string& LedgerError::code() const noexcept { return code_; }
LedgerDurabilityBoundary LedgerError::durability_boundary() const noexcept { return boundary_; }
std::uint64_t LedgerError::bytes_written() const noexcept { return bytes_written_; }

std::string ledger_record_json(const LedgerRecord& record) {
  auto object = record_without_hash(record);
  object.emplace("record_hash", text(record.record_hash));
  return canonical_json(JsonValue(std::move(object)));
}
LedgerVerificationResult verify_ledger(const std::filesystem::path& path,
                                       LedgerVerificationMode mode) {
  return scan(path, mode, {});
}
LedgerVerificationResult visit_verified_ledger(const std::filesystem::path& path,
                                                const LedgerRecordVisitor& visitor) {
  return scan(path, LedgerVerificationMode::MetadataOnly, visitor);
}

ExecutionLedger::ExecutionLedger(std::filesystem::path path, int descriptor,
                                 std::uint64_t device, std::uint64_t inode,
                                 std::uint64_t sequence, std::string hash,
                                 LedgerFaultHook fault_hook)
    : path_(std::move(path)), descriptor_(descriptor), device_(device), inode_(inode),
      last_sequence_(sequence), last_hash_(std::move(hash)), fault_hook_(std::move(fault_hook)) {}

ExecutionLedger ExecutionLedger::create_new(const std::filesystem::path& raw_path,
                                             LedgerFaultHook fault_hook) {
  const auto path = absolute_normalized(raw_path);
  if (!safe_parent(path)) throw LedgerError("ledger_unsafe_parent");
  const int descriptor = ::open(path.c_str(), O_CREAT | O_EXCL | O_APPEND | O_WRONLY | O_CLOEXEC |
                                                  O_NOFOLLOW, 0600);
  if (descriptor < 0) throw LedgerError("ledger_create_failed");
  if (::flock(descriptor, LOCK_EX | LOCK_NB) != 0) {
    ::close(descriptor);
    throw LedgerError("ledger_locked");
  }
  struct stat status {};
  if (::fstat(descriptor, &status) != 0 || !S_ISREG(status.st_mode) || status.st_nlink != 1) {
    ::close(descriptor);
    throw LedgerError("ledger_unsafe_file");
  }
  return ExecutionLedger(path, descriptor, static_cast<std::uint64_t>(status.st_dev),
                         static_cast<std::uint64_t>(status.st_ino), 0,
                         std::string(kGenesisHash), std::move(fault_hook));
}

ExecutionLedger ExecutionLedger::open_existing(const std::filesystem::path& raw_path,
                                                LedgerFaultHook fault_hook) {
  const auto path = absolute_normalized(raw_path);
  auto verification = verify_ledger(path);
  if (!verification.clean()) throw LedgerError(verification.error_code);
  struct stat linked {};
  if (!safe_file(path, &linked)) throw LedgerError("ledger_unsafe_file");
  const int descriptor = ::open(path.c_str(), O_APPEND | O_WRONLY | O_CLOEXEC | O_NOFOLLOW);
  if (descriptor < 0) throw LedgerError("ledger_open_failed");
  if (::flock(descriptor, LOCK_EX | LOCK_NB) != 0) {
    ::close(descriptor);
    throw LedgerError("ledger_locked");
  }
  struct stat opened {};
  if (::fstat(descriptor, &opened) != 0 || linked.st_dev != opened.st_dev ||
      linked.st_ino != opened.st_ino || opened.st_nlink != 1) {
    ::close(descriptor);
    throw LedgerError("ledger_identity_changed");
  }
  verification = verify_ledger(path);
  const auto device = static_cast<std::uint64_t>(opened.st_dev);
  const auto inode = static_cast<std::uint64_t>(opened.st_ino);
  if (!verification.clean() || !path_matches(path, device, inode, descriptor)) {
    ::close(descriptor);
    throw LedgerError(verification.clean() ? "ledger_identity_changed" : verification.error_code);
  }
  return ExecutionLedger(path, descriptor, device, inode, verification.verified_records,
                         verification.last_record_hash, std::move(fault_hook));
}

ExecutionLedger::ExecutionLedger(ExecutionLedger&& other) noexcept
    : path_(std::move(other.path_)), descriptor_(other.descriptor_), device_(other.device_),
      inode_(other.inode_), last_sequence_(other.last_sequence_),
      last_hash_(std::move(other.last_hash_)), fault_hook_(std::move(other.fault_hook_)) {
  other.descriptor_ = -1;
}
ExecutionLedger& ExecutionLedger::operator=(ExecutionLedger&& other) noexcept {
  if (this != &other) {
    close();
    path_ = std::move(other.path_);
    descriptor_ = other.descriptor_;
    device_ = other.device_;
    inode_ = other.inode_;
    last_sequence_ = other.last_sequence_;
    last_hash_ = std::move(other.last_hash_);
    fault_hook_ = std::move(other.fault_hook_);
    other.descriptor_ = -1;
  }
  return *this;
}
ExecutionLedger::~ExecutionLedger() { close(); }
void ExecutionLedger::close() noexcept {
  if (descriptor_ >= 0) { ::close(descriptor_); descriptor_ = -1; }
}

LedgerRecord ExecutionLedger::append(const ExecutionEvent& event) {
  if (descriptor_ < 0) throw LedgerError("ledger_closed");
  try { static_cast<void>(ExecutionEvent::parse(event.to_json())); }
  catch (const JsonError& error) { throw LedgerError(error.code()); }
  if (!path_matches(path_, device_, inode_, descriptor_)) {
    close();
    throw LedgerError("ledger_identity_changed");
  }
  bool duplicate = false;
  const auto current = visit_verified_ledger(path_, [&](const LedgerRecord& record) {
    if (record.event.event_id == event.event_id) duplicate = true;
  });
  if (!current.clean() || current.verified_records != last_sequence_ ||
      current.last_record_hash != last_hash_) {
    close();
    throw LedgerError(current.clean() ? "ledger_state_changed" : current.error_code);
  }
  if (duplicate) throw LedgerError("ledger_duplicate_event_id");
  LedgerRecord record{last_sequence_ + 1, event, last_hash_, {}};
  record.record_hash = sha256_hex(canonical_json(JsonValue(record_without_hash(record))));
  auto line = ledger_record_json(record);
  line.push_back('\n');
  if (line.size() > kMaximumLedgerRecordBytes) throw LedgerError("ledger_record_size");

  std::uint64_t written{};
  try {
    injected(fault_hook_, LedgerFaultPoint::BeforeWrite, LedgerDurabilityBoundary::NotWritten, 0);
    if (!path_matches(path_, device_, inode_, descriptor_)) {
      throw LedgerError("ledger_identity_changed");
    }
    if (fault_hook_ && line.size() > 1) {
      const auto midpoint = line.size() / 2U;
      write_all(descriptor_, std::string_view(line).substr(0, midpoint), written);
      injected(fault_hook_, LedgerFaultPoint::AfterPartialWrite,
               LedgerDurabilityBoundary::Uncertain, written);
      write_all(descriptor_, std::string_view(line).substr(midpoint), written);
    } else {
      write_all(descriptor_, line, written);
    }
    injected(fault_hook_, LedgerFaultPoint::BeforeFsync,
             LedgerDurabilityBoundary::Uncertain, written);
    if (::fsync(descriptor_) != 0) {
      throw LedgerError("ledger_fsync_failed", LedgerDurabilityBoundary::Uncertain, written);
    }
    injected(fault_hook_, LedgerFaultPoint::AfterFsync,
             LedgerDurabilityBoundary::Durable, written);
    if (!path_matches(path_, device_, inode_, descriptor_)) {
      throw LedgerError("ledger_identity_changed", LedgerDurabilityBoundary::Uncertain, written);
    }
  } catch (...) {
    close();
    throw;
  }
  last_sequence_ = record.sequence;
  last_hash_ = record.record_hash;
  return record;
}
}  // namespace shaurya::execution
