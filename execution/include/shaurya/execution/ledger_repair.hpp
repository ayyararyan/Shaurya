#pragma once

#include <cstdint>
#include <filesystem>
#include <string>

namespace shaurya::execution {
struct LedgerRepairRequest {
  std::filesystem::path input;
  std::filesystem::path output;
  std::string confirmation;
  std::string execution_session_id;
  std::string event_id;
  std::int64_t timestamp_ns{};
  std::filesystem::path active_segment;
};
struct LedgerRepairResult { std::uint64_t copied_records{}; std::uint64_t verified_prefix_bytes{}; std::string damaged_sha256; };
[[nodiscard]] LedgerRepairResult repair_truncated_ledger(const LedgerRepairRequest& request);
}  // namespace shaurya::execution
