#include "shaurya/execution/ledger_repair.hpp"

#include "shaurya/execution/canonical_json.hpp"
#include "shaurya/execution/execution_ledger.hpp"
#include "shaurya/execution/ledger_replay.hpp"
#include "test_support.hpp"

#include <fstream>
#include <sys/stat.h>

using namespace shaurya::execution;
namespace {
std::string bytes(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  return {std::istreambuf_iterator<char>(input), {}};
}
void make_read_only(const std::filesystem::path& path) {
  std::filesystem::permissions(path, std::filesystem::perms::owner_read,
                               std::filesystem::perm_options::replace);
}
bool owner_read_only(const std::filesystem::path& path) {
  struct stat status {};
  return ::lstat(path.c_str(), &status) == 0 && (status.st_mode & 0777) == 0400;
}
LedgerRepairRequest request_for(const std::filesystem::path& source,
                                const std::filesystem::path& output,
                                const std::filesystem::path& active) {
  return {source, output, "REPAIR_TRUNCATED_LEDGER",
          "00000000-0000-4000-8000-000000000003",
          "00000000-0000-4000-8000-000000000109", 200, active};
}
}

int main() {
  const auto root = test_directory("repair");
  const auto source = root / "damaged.jsonl";
  const auto output = root / "repaired.jsonl";
  const auto configured_active = root / "configured-active.jsonl";
  {
    auto ledger = ExecutionLedger::create_new(source);
    static_cast<void>(ledger.append(
        event("00000000-0000-4000-8000-000000000101", "session_started")));
  }
  std::ofstream(source, std::ios::app | std::ios::binary) << "{\"event_id\"";
  make_read_only(source);
  const auto original = bytes(source);
  auto request = request_for(source, output, configured_active);

  request.confirmation = "WRONG";
  try {
    static_cast<void>(repair_truncated_ledger(request));
    require_test(false, "confirmation accepted");
  } catch (const LedgerError& error) {
    require_test(error.code() == "repair_confirmation_required", "confirmation code");
  }
  require_test(!std::filesystem::exists(output) && bytes(source) == original &&
                   owner_read_only(source),
               "unconfirmed repair changed evidence");
  request.confirmation = "REPAIR_TRUNCATED_LEDGER";

  request.active_segment = source;
  try {
    static_cast<void>(repair_truncated_ledger(request));
    require_test(false, "active segment repaired");
  } catch (const LedgerError& error) {
    require_test(error.code() == "repair_source_is_active_segment", "active segment code");
  }
  request.active_segment = configured_active;
  const auto active_alias = root / "active-hardlink.jsonl";
  std::filesystem::create_hard_link(source, active_alias);
  request.active_segment = active_alias;
  try {
    static_cast<void>(repair_truncated_ledger(request));
    require_test(false, "hard-linked active segment repaired");
  } catch (const LedgerError& error) {
    require_test(error.code() == "repair_source_is_active_segment", "active alias code");
  }
  std::filesystem::remove(active_alias);
  request.active_segment = configured_active;

  const auto existing_output = root / "existing.jsonl";
  std::ofstream(existing_output) << "occupied";
  request.output = existing_output;
  try {
    static_cast<void>(repair_truncated_ledger(request));
    require_test(false, "existing output accepted");
  } catch (const LedgerError& error) {
    require_test(error.code() == "repair_output_create_failed", "existing output code");
  }
  require_test(bytes(existing_output) == "occupied" && bytes(source) == original,
               "existing output or source changed");

  request.output = source;
  try {
    static_cast<void>(repair_truncated_ledger(request));
    require_test(false, "aliased output accepted");
  } catch (const LedgerError& error) {
    require_test(error.code() == "repair_output_aliases_input", "alias code");
  }
  const auto output_alias = root / "output-hardlink.jsonl";
  std::filesystem::create_hard_link(source, output_alias);
  request.output = output_alias;
  try {
    static_cast<void>(repair_truncated_ledger(request));
    require_test(false, "hard-linked output alias accepted");
  } catch (const LedgerError& error) {
    require_test(error.code() == "repair_output_aliases_input", "output alias code");
  }
  std::filesystem::remove(output_alias);

  const auto linked_parent_target = root / "linked-parent-target";
  std::filesystem::create_directory(linked_parent_target);
  std::filesystem::permissions(linked_parent_target, std::filesystem::perms::owner_all,
                               std::filesystem::perm_options::replace);
  const auto linked_parent = root / "linked-parent";
  std::filesystem::create_directory_symlink(linked_parent_target, linked_parent);
  request.output = linked_parent / "unsafe.jsonl";
  try {
    static_cast<void>(repair_truncated_ledger(request));
    require_test(false, "symlinked output ancestor accepted");
  } catch (const LedgerError& error) {
    require_test(error.code() == "repair_unsafe_path", "symlinked ancestor code");
  }

  const auto linked_input_parent = root / "linked-input-parent";
  std::filesystem::create_directory_symlink(root, linked_input_parent);
  request.input = linked_input_parent / source.filename();
  request.output = root / "unsafe-input-output.jsonl";
  try {
    static_cast<void>(repair_truncated_ledger(request));
    require_test(false, "symlinked input ancestor accepted");
  } catch (const LedgerError& error) {
    require_test(error.code() == "repair_unsafe_path", "symlinked input code");
  }

  request.input = source;
  request.output = output;
  const auto repaired = repair_truncated_ledger(request);
  require_test(repaired.copied_records == 1 && repaired.damaged_sha256 == sha256_hex(original) &&
                   bytes(source) == original && owner_read_only(source),
               "damaged evidence was not preserved read-only");
  const auto verified = verify_ledger(output, LedgerVerificationMode::RetainRecords);
  require_test(verified.clean() && verified.records.size() == 2 &&
                   verified.records.back().event.event_type == "ledger_repair_recorded" &&
                   replay_ledger(output).reconciliation_required,
               "repair incident or reconciliation blocker missing");

  const auto writable = root / "writable.jsonl";
  {
    auto ledger = ExecutionLedger::create_new(writable);
    static_cast<void>(ledger.append(
        event("00000000-0000-4000-8000-000000000121", "session_started")));
  }
  std::ofstream(writable, std::ios::app | std::ios::binary) << "{\"event_id\"";
  auto writable_request = request_for(writable, root / "writable-output.jsonl", configured_active);
  try {
    static_cast<void>(repair_truncated_ledger(writable_request));
    require_test(false, "writable evidence accepted");
  } catch (const LedgerError& error) {
    require_test(error.code() == "repair_source_not_read_only", "writable evidence code");
  }

  const auto malformed = root / "malformed.jsonl";
  {
    auto ledger = ExecutionLedger::create_new(malformed);
    static_cast<void>(ledger.append(
        event("00000000-0000-4000-8000-000000000131", "session_started")));
  }
  std::ofstream(malformed, std::ios::app | std::ios::binary) << "{\"event_id\":truX}";
  make_read_only(malformed);
  auto malformed_request = request_for(malformed, root / "must-not-exist.jsonl",
                                       configured_active);
  try {
    static_cast<void>(repair_truncated_ledger(malformed_request));
    require_test(false, "malformed tail repaired");
  } catch (const LedgerError& error) {
    require_test(error.code() == "repair_source_not_truncated_tail", "malformed repair code");
  }
  require_test(!std::filesystem::exists(malformed_request.output),
               "malformed source created output");
  std::filesystem::remove_all(root);
}
