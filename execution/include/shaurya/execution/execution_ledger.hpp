#pragma once

#include "shaurya/execution/contracts.hpp"

#include <cstdint>
#include <filesystem>
#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace shaurya::execution {

inline constexpr std::size_t kMaximumLedgerRecordBytes = 64U * 1024U;

enum class LedgerDurabilityBoundary { NotWritten, Uncertain, Durable };

class LedgerError : public std::runtime_error {
 public:
  explicit LedgerError(std::string code,
                       LedgerDurabilityBoundary boundary = LedgerDurabilityBoundary::NotWritten,
                       std::uint64_t bytes_written = 0);
  [[nodiscard]] const std::string& code() const noexcept;
  [[nodiscard]] LedgerDurabilityBoundary durability_boundary() const noexcept;
  [[nodiscard]] std::uint64_t bytes_written() const noexcept;
 private:
  std::string code_;
  LedgerDurabilityBoundary boundary_;
  std::uint64_t bytes_written_{};
};

struct LedgerRecord {
  std::uint64_t sequence{};
  ExecutionEvent event;
  std::string previous_record_hash;
  std::string record_hash;
};

enum class LedgerVerificationStatus { Clean, TruncatedTail, Corrupt, Unsafe };
enum class LedgerVerificationMode { MetadataOnly, RetainRecords };

struct LedgerVerificationResult {
  LedgerVerificationStatus status{LedgerVerificationStatus::Corrupt};
  std::string error_code;
  std::uint64_t verified_records{};
  std::uint64_t verified_prefix_bytes{};
  std::string last_record_hash{64, '0'};
  std::vector<LedgerRecord> records;
  [[nodiscard]] bool clean() const noexcept { return status == LedgerVerificationStatus::Clean; }
};

[[nodiscard]] LedgerVerificationResult verify_ledger(
    const std::filesystem::path& path,
    LedgerVerificationMode mode = LedgerVerificationMode::MetadataOnly);
using LedgerRecordVisitor = std::function<void(const LedgerRecord&)>;
[[nodiscard]] LedgerVerificationResult visit_verified_ledger(
    const std::filesystem::path& path, const LedgerRecordVisitor& visitor);
[[nodiscard]] std::string ledger_record_json(const LedgerRecord& record);

enum class LedgerFaultPoint { BeforeWrite, AfterPartialWrite, BeforeFsync, AfterFsync };
using LedgerFaultHook = std::function<void(LedgerFaultPoint)>;

class ExecutionLedger {
 public:
  [[nodiscard]] static ExecutionLedger create_new(const std::filesystem::path& path,
                                                  LedgerFaultHook fault_hook = {});
  [[nodiscard]] static ExecutionLedger open_existing(const std::filesystem::path& path,
                                                     LedgerFaultHook fault_hook = {});
  [[nodiscard]] static ExecutionLedger create_new_at(int directory_descriptor,
                                                     std::string basename,
                                                     LedgerFaultHook fault_hook = {});
  [[nodiscard]] static ExecutionLedger open_existing_at(int directory_descriptor,
                                                        std::string basename,
                                                        LedgerFaultHook fault_hook = {});
  ExecutionLedger(ExecutionLedger&& other) noexcept;
  ExecutionLedger& operator=(ExecutionLedger&& other) noexcept;
  ExecutionLedger(const ExecutionLedger&) = delete;
  ExecutionLedger& operator=(const ExecutionLedger&) = delete;
  ~ExecutionLedger();

  [[nodiscard]] LedgerRecord append(const ExecutionEvent& event);
  [[nodiscard]] LedgerVerificationResult verify(
      LedgerVerificationMode mode = LedgerVerificationMode::MetadataOnly) const;
  [[nodiscard]] std::uint64_t last_sequence() const noexcept { return last_sequence_; }
  [[nodiscard]] const std::string& last_hash() const noexcept { return last_hash_; }

 private:
  ExecutionLedger(std::filesystem::path path, int parent_descriptor, std::string basename,
                  int descriptor, std::uint64_t device,
                  std::uint64_t inode, std::uint64_t sequence, std::string hash,
                  LedgerFaultHook fault_hook);
  void close() noexcept;
  std::filesystem::path path_;
  int parent_descriptor_{-1};
  std::string basename_;
  int descriptor_{-1};
  std::uint64_t device_{};
  std::uint64_t inode_{};
  std::uint64_t last_sequence_{};
  std::string last_hash_{64, '0'};
  LedgerFaultHook fault_hook_;
};

}  // namespace shaurya::execution
