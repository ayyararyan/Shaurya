#include "shaurya/execution/execution_ledger.hpp"
#include "test_support.hpp"

#include <array>
#include <fcntl.h>
#include <fstream>
#include <sys/stat.h>
#include <unistd.h>

using namespace shaurya::execution;

namespace {
std::string bytes(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  return {std::istreambuf_iterator<char>(input), {}};
}
void write_bytes(const std::filesystem::path& path, std::string_view value) {
  std::ofstream output(path, std::ios::binary | std::ios::trunc);
  output.write(value.data(), static_cast<std::streamsize>(value.size()));
  output.close();
  std::filesystem::permissions(path,
      std::filesystem::perms::owner_read | std::filesystem::perms::owner_write,
      std::filesystem::perm_options::replace);
}
void require_corrupt_copy(const std::filesystem::path& path, std::string value,
                          std::string_view message) {
  write_bytes(path, value);
  require_test(verify_ledger(path).status == LedgerVerificationStatus::Corrupt, message);
}
}  // namespace

int main() {
  const auto root = test_directory("ledger");
  const auto path = root / "ledger.jsonl";
  {
    auto ledger = ExecutionLedger::create_new(path);
    const auto first = ledger.append(
        event("00000000-0000-4000-8000-000000000101", "session_started"));
    require_test(first.sequence == 1 && first.previous_record_hash == std::string(64, '0'),
                 "genesis");
    const auto intent = event(
        "00000000-0000-4000-8000-000000000102", "intent_received",
        {{"semantic_fingerprint", JsonValue(std::string(64, 'a'))}},
        "00000000-0000-4000-8000-000000000001");
    const auto second = ledger.append(intent);
    require_test(second.sequence == 2 && second.previous_record_hash == first.record_hash, "chain");
    try {
      static_cast<void>(ledger.append(intent));
      require_test(false, "duplicate event id accepted");
    } catch (const LedgerError& error) {
      require_test(error.code() == "ledger_duplicate_event_id", "duplicate event code");
    }
    try {
      auto duplicate = ExecutionLedger::open_existing(path);
      static_cast<void>(duplicate);
      require_test(false, "second writer accepted");
    } catch (const LedgerError& error) {
      require_test(error.code() == "ledger_locked", "lock code");
    }
  }

  auto verified = verify_ledger(path, LedgerVerificationMode::RetainRecords);
  require_test(verified.clean() && verified.records.size() == 2, "verify");
  const auto original = bytes(path);
  require_test(!original.empty() && original.back() == '\n', "newline termination");
  for (const auto& record : verified.records) {
    require_test(record.record_hash.size() == 64 && ledger_record_json(record).front() == '{',
                 "canonical record");
  }

  {
    auto ledger = ExecutionLedger::open_existing(path);
    require_test(ledger.last_sequence() == 2, "reopen sequence");
    static_cast<void>(ledger.append(
        event("00000000-0000-4000-8000-000000000103", "session_stopped")));
  }
  require_test(verify_ledger(path).verified_records == 3, "continue chain");
  const auto baseline = bytes(path);

  const auto partial = root / "partial.jsonl";
  write_bytes(partial, baseline + "{\"event_id\"");
  const auto truncated = verify_ledger(partial);
  require_test(truncated.status == LedgerVerificationStatus::TruncatedTail &&
                   truncated.verified_records == 3 &&
                   truncated.verified_prefix_bytes == baseline.size(),
               "truncated tail");

  require_corrupt_copy(root / "malformed-final.jsonl", baseline + "{\"partial\":true}\n",
                       "newline malformed final");
  require_corrupt_copy(root / "missing-newline.jsonl", baseline + "{}",
                       "complete final without newline");
  require_corrupt_copy(root / "malformed-no-newline.jsonl", baseline + "{\"event_id\":truX}",
                       "malformed tail classified as repairable");

  auto tampered = baseline;
  const auto event_type = tampered.find("session_started");
  require_test(event_type != std::string::npos, "tamper target");
  tampered.replace(event_type, std::string("session_started").size(), "session_stopped");
  require_corrupt_copy(root / "tampered.jsonl", tampered, "tampered middle record");

  auto noncanonical = baseline;
  noncanonical.insert(noncanonical.find('\n'), " ");
  require_corrupt_copy(root / "noncanonical.jsonl", noncanonical, "noncanonical record");

  const auto unsafe = root / "unsafe.jsonl";
  write_bytes(unsafe, baseline);
  std::filesystem::permissions(unsafe, std::filesystem::perms::owner_all |
                                      std::filesystem::perms::group_read,
                               std::filesystem::perm_options::replace);
  require_test(verify_ledger(unsafe).status == LedgerVerificationStatus::Unsafe,
               "unsafe permissions");

  const auto link = root / "link.jsonl";
  std::filesystem::create_symlink(path, link);
  require_test(verify_ledger(link).status == LedgerVerificationStatus::Unsafe, "symlink");

  const auto real_parent = root / "real-parent";
  std::filesystem::create_directory(real_parent);
  std::filesystem::permissions(real_parent, std::filesystem::perms::owner_all,
                               std::filesystem::perm_options::replace);
  const auto ancestor_link = root / "ancestor-link";
  std::filesystem::create_directory_symlink(real_parent, ancestor_link);
  try {
    static_cast<void>(ExecutionLedger::create_new(ancestor_link / "ledger.jsonl"));
    require_test(false, "symlinked ancestor accepted");
  } catch (const LedgerError& error) {
    require_test(error.code() == "ledger_unsafe_parent", "symlink ancestor code");
  }

  const auto replacement = root / "replacement.jsonl";
  {
    auto ledger = ExecutionLedger::create_new(replacement);
    static_cast<void>(ledger.append(
        event("00000000-0000-4000-8000-000000000151", "session_started")));
    std::filesystem::rename(replacement, root / "replacement-original.jsonl");
    write_bytes(replacement, {});
    try {
      static_cast<void>(ledger.append(
          event("00000000-0000-4000-8000-000000000152", "session_stopped")));
      require_test(false, "replacement accepted");
    } catch (const LedgerError& error) {
      require_test(error.code() == "ledger_identity_changed", "replacement code");
    }
  }

  const auto secret_path = root / "secret.jsonl";
  {
    auto ledger = ExecutionLedger::create_new(secret_path);
    try {
      static_cast<void>(ledger.append(event(
          "00000000-0000-4000-8000-000000000161", "session_started",
          {{"password", JsonValue(std::string("must-not-appear-in-error"))}})));
      require_test(false, "secret payload accepted");
    } catch (const LedgerError& error) {
      require_test(std::string(error.what()).find("must-not-appear") == std::string::npos,
                   "secret echoed");
    }
  }

  struct FaultCase {
    LedgerFaultPoint point;
    LedgerDurabilityBoundary boundary;
    LedgerVerificationStatus status;
    std::string_view name;
  };
  constexpr std::array fault_cases{
      FaultCase{LedgerFaultPoint::BeforeWrite, LedgerDurabilityBoundary::NotWritten,
                LedgerVerificationStatus::Clean, "before-write"},
      FaultCase{LedgerFaultPoint::AfterPartialWrite, LedgerDurabilityBoundary::Uncertain,
                LedgerVerificationStatus::TruncatedTail, "partial-write"},
      FaultCase{LedgerFaultPoint::BeforeFsync, LedgerDurabilityBoundary::Uncertain,
                LedgerVerificationStatus::Clean, "before-fsync"},
      FaultCase{LedgerFaultPoint::AfterFsync, LedgerDurabilityBoundary::Durable,
                LedgerVerificationStatus::Clean, "after-fsync"},
  };
  std::uint64_t fault_id = 170;
  for (const auto& fault : fault_cases) {
    const auto fault_path = root / (std::string(fault.name) + ".jsonl");
    auto ledger = ExecutionLedger::create_new(fault_path, [&](LedgerFaultPoint point) {
      if (point == fault.point) throw std::runtime_error("injected");
    });
    try {
      const auto suffix = std::to_string(fault_id++);
      static_cast<void>(ledger.append(event(
          "00000000-0000-4000-8000-000000000" + suffix, "session_started")));
      require_test(false, "fault injection did not fire");
    } catch (const LedgerError& error) {
      require_test(error.code() == "ledger_injected_failure" &&
                       error.durability_boundary() == fault.boundary &&
                       ((fault.boundary == LedgerDurabilityBoundary::NotWritten) ==
                        (error.bytes_written() == 0)),
                   "durability boundary mismatch");
    }
    require_test(verify_ledger(fault_path).status == fault.status, "fault recovery classification");
  }

  const auto race_path = root / "race.jsonl";
  const auto displaced = root / "race-displaced.jsonl";
  bool replace = false;
  {
    auto ledger = ExecutionLedger::create_new(race_path, [&](LedgerFaultPoint point) {
      if (replace && point == LedgerFaultPoint::BeforeWrite) {
        std::filesystem::rename(race_path, displaced);
        write_bytes(race_path, {});
      }
    });
    static_cast<void>(ledger.append(
        event("00000000-0000-4000-8000-000000000181", "session_started")));
    replace = true;
    try {
      static_cast<void>(ledger.append(
          event("00000000-0000-4000-8000-000000000182", "session_stopped")));
      require_test(false, "replacement race append succeeded");
    } catch (const LedgerError& error) {
      require_test(error.code() == "ledger_identity_changed" &&
                       error.durability_boundary() == LedgerDurabilityBoundary::NotWritten,
                   "replacement race boundary");
    }
  }
  require_test(verify_ledger(displaced).verified_records == 1 &&
                   verify_ledger(race_path).verified_records == 0,
               "replacement race wrote wrong inode");

  const auto postwrite_path = root / "postwrite-race.jsonl";
  const auto postwrite_displaced = root / "postwrite-displaced.jsonl";
  bool replace_after_fsync = false;
  {
    auto ledger = ExecutionLedger::create_new(postwrite_path, [&](LedgerFaultPoint point) {
      if (replace_after_fsync && point == LedgerFaultPoint::AfterFsync) {
        std::filesystem::rename(postwrite_path, postwrite_displaced);
        write_bytes(postwrite_path, {});
      }
    });
    static_cast<void>(ledger.append(
        event("00000000-0000-4000-8000-000000000191", "session_started")));
    replace_after_fsync = true;
    try {
      static_cast<void>(ledger.append(
          event("00000000-0000-4000-8000-000000000192", "session_stopped")));
      require_test(false, "post-fsync replacement was reported successful");
    } catch (const LedgerError& error) {
      require_test(error.code() == "ledger_identity_changed" &&
                       error.durability_boundary() == LedgerDurabilityBoundary::Uncertain,
                   "post-fsync replacement boundary");
    }
  }
  require_test(verify_ledger(postwrite_displaced).verified_records == 2 &&
                   verify_ledger(postwrite_path).verified_records == 0,
               "post-fsync replacement durable evidence mismatch");

  const auto streamed = verify_ledger(path);
  require_test(streamed.records.empty() && streamed.verified_records == 3,
               "metadata verification retained segment records");

  const auto descriptor_root = root / "descriptor-root";
  const auto displaced_root = root / "descriptor-root-displaced";
  std::filesystem::create_directory(descriptor_root);
  (void)::chmod(descriptor_root.c_str(), 0700);
  const int root_descriptor = ::open(descriptor_root.c_str(),
                                     O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
  require_test(root_descriptor >= 0, "descriptor-root fixture open failed");
  {
    auto ledger = ExecutionLedger::create_new_at(root_descriptor, "events.jsonl");
    std::filesystem::rename(descriptor_root, displaced_root);
    std::filesystem::create_directory(descriptor_root);
    (void)::chmod(descriptor_root.c_str(), 0700);
    static_cast<void>(ledger.append(
        event("00000000-0000-4000-8000-000000000199", "session_started")));
    require_test(ledger.verify().clean() && ledger.last_sequence() == 1U,
                 "descriptor-root ledger lost authority after pathname replacement");
  }
  (void)::close(root_descriptor);
  require_test(verify_ledger(displaced_root / "events.jsonl").verified_records == 1U &&
                   !std::filesystem::exists(descriptor_root / "events.jsonl"),
               "descriptor-root ledger followed a replaced pathname");

  std::filesystem::remove_all(root);
}
