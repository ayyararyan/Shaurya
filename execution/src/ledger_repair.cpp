#include "shaurya/execution/ledger_repair.hpp"

#include "shaurya/execution/canonical_json.hpp"
#include "shaurya/execution/execution_ledger.hpp"

#include <cerrno>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

namespace shaurya::execution {
namespace {
std::filesystem::path absolute_normalized(const std::filesystem::path& path) {
  std::error_code error;
  auto result = std::filesystem::absolute(path, error);
  if (error) throw LedgerError("repair_invalid_path");
  return result.lexically_normal();
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
  const auto parent = path.parent_path();
  return !parent.empty() && ::lstat(parent.c_str(), &status) == 0 && S_ISDIR(status.st_mode) &&
         status.st_uid == ::geteuid() && (status.st_mode & 0077) == 0;
}

void write_all(int descriptor, std::string_view bytes) {
  while (!bytes.empty()) {
    const auto count = ::write(descriptor, bytes.data(), bytes.size());
    if (count < 0) {
      if (errno == EINTR) continue;
      throw LedgerError("repair_write_failed");
    }
    if (count == 0) throw LedgerError("repair_write_failed");
    bytes.remove_prefix(static_cast<std::size_t>(count));
  }
}

std::string read_source(int descriptor) {
  std::string bytes;
  char buffer[8192];
  for (;;) {
    const auto count = ::read(descriptor, buffer, sizeof(buffer));
    if (count == 0) break;
    if (count < 0) {
      if (errno == EINTR) continue;
      throw LedgerError("repair_read_failed");
    }
    if (bytes.size() + static_cast<std::size_t>(count) > 64U * 1024U * 1024U) {
      throw LedgerError("repair_source_unbounded");
    }
    bytes.append(buffer, static_cast<std::size_t>(count));
  }
  return bytes;
}
}  // namespace

LedgerRepairResult repair_truncated_ledger(const LedgerRepairRequest& request) {
  if (request.confirmation != "REPAIR_TRUNCATED_LEDGER") {
    throw LedgerError("repair_confirmation_required");
  }
  if (request.active_segment.empty()) throw LedgerError("repair_active_segment_required");
  const auto input_path = absolute_normalized(request.input);
  const auto output_path = absolute_normalized(request.output);
  const auto active_path = absolute_normalized(request.active_segment);
  if (input_path == active_path) throw LedgerError("repair_source_is_active_segment");
  std::error_code equivalent_error;
  if (std::filesystem::exists(active_path, equivalent_error) && !equivalent_error &&
      std::filesystem::equivalent(input_path, active_path, equivalent_error) && !equivalent_error) {
    throw LedgerError("repair_source_is_active_segment");
  }
  if (input_path == output_path) {
    throw LedgerError("repair_output_aliases_input");
  }
  equivalent_error.clear();
  if (std::filesystem::exists(output_path, equivalent_error) && !equivalent_error &&
      std::filesystem::equivalent(input_path, output_path, equivalent_error) && !equivalent_error) {
    throw LedgerError("repair_output_aliases_input");
  }
  if (!ancestors_have_no_symlink(input_path) || !safe_parent(output_path)) {
    throw LedgerError("repair_unsafe_path");
  }
  const int source_descriptor = ::open(input_path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (source_descriptor < 0) throw LedgerError("repair_read_failed");
  struct SourceLock {
    int descriptor;
    ~SourceLock() { if (descriptor >= 0) ::close(descriptor); }
  } source_lock{source_descriptor};
  if (::flock(source_descriptor, LOCK_SH | LOCK_NB) != 0) {
    throw LedgerError("repair_source_active");
  }
  struct stat locked_status {}, linked_status {};
  if (::fstat(source_descriptor, &locked_status) != 0 || !S_ISREG(locked_status.st_mode) ||
      locked_status.st_uid != ::geteuid() || (locked_status.st_mode & 0077) != 0 ||
      ::lstat(input_path.c_str(), &linked_status) != 0 ||
      linked_status.st_dev != locked_status.st_dev || linked_status.st_ino != locked_status.st_ino) {
    throw LedgerError("repair_source_identity_changed");
  }
  if ((locked_status.st_mode & 0222) != 0) throw LedgerError("repair_source_not_read_only");
  const auto verification = verify_ledger(input_path);
  if (verification.status != LedgerVerificationStatus::TruncatedTail) {
    throw LedgerError("repair_source_not_truncated_tail");
  }
  const auto source = read_source(source_descriptor);
  if (::lstat(input_path.c_str(), &linked_status) != 0 ||
      linked_status.st_dev != locked_status.st_dev || linked_status.st_ino != locked_status.st_ino) {
    throw LedgerError("repair_source_identity_changed");
  }
  if (verification.verified_prefix_bytes > source.size()) throw LedgerError("repair_invalid_prefix");
  const auto damaged_sha256 = sha256_hex(source);
  ExecutionEvent incident;
  incident.event_id = request.event_id;
  incident.event_type = "ledger_repair_recorded";
  incident.timestamp_ns = request.timestamp_ns;
  incident.execution_session_id = request.execution_session_id;
  incident.payload = {
      {"confirmation_type", JsonValue(std::string("REPAIR_TRUNCATED_LEDGER"))},
      {"damaged_segment_bytes", JsonValue(JsonInteger{std::to_string(source.size())})},
      {"damaged_segment_sha256", JsonValue(damaged_sha256)},
      {"repair_tool_version", JsonValue(std::string("1.0.0"))},
      {"source_label", JsonValue(input_path.filename().string())},
      {"verified_prefix_bytes",
       JsonValue(JsonInteger{std::to_string(verification.verified_prefix_bytes)})},
  };
  try {
    static_cast<void>(ExecutionEvent::parse(incident.to_json()));
  } catch (const JsonError& error) {
    throw LedgerError(error.code());
  }

  const int output = ::open(output_path.c_str(), O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC |
                                                        O_NOFOLLOW, 0600);
  if (output < 0) throw LedgerError("repair_output_create_failed");
  try {
    write_all(output, std::string_view(source).substr(0, verification.verified_prefix_bytes));
    if (::fsync(output) != 0) throw LedgerError("repair_fsync_failed");
    if (::close(output) != 0) throw LedgerError("repair_close_failed");
  } catch (...) {
    ::close(output);
    throw;
  }

  try {
    auto copied = verify_ledger(output_path);
    if (!copied.clean() || copied.verified_records != verification.verified_records) {
      throw LedgerError("repair_copy_verification_failed");
    }
    auto ledger = ExecutionLedger::open_existing(output_path);
    static_cast<void>(ledger.append(incident));
  } catch (...) {
    throw;
  }

  const int parent = ::open(output_path.parent_path().c_str(), O_RDONLY | O_CLOEXEC);
  if (parent < 0 || ::fsync(parent) != 0) {
    if (parent >= 0) ::close(parent);
    throw LedgerError("repair_parent_fsync_failed");
  }
  ::close(parent);
  struct stat preserved_status {};
  if (::fstat(source_descriptor, &preserved_status) != 0 ||
      preserved_status.st_dev != locked_status.st_dev ||
      preserved_status.st_ino != locked_status.st_ino || (preserved_status.st_mode & 0222) != 0) {
    throw LedgerError("repair_source_evidence_changed");
  }
  return {verification.verified_records, verification.verified_prefix_bytes, damaged_sha256};
}
}  // namespace shaurya::execution
