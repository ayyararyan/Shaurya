#pragma once

#include "shaurya/execution/routing_snapshot.hpp"

#include <filesystem>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>

namespace shaurya::execution {

enum class RoutingErrorCode {
  Stale,
  Missing,
  Malformed,
  Duplicate,
  Partial,
  Tampered,
  Unsupported,
  Unsafe,
  NotFound,
};

class RoutingError : public std::runtime_error {
 public:
  explicit RoutingError(RoutingErrorCode code);
  [[nodiscard]] RoutingErrorCode code() const noexcept;

 private:
  RoutingErrorCode code_;
};

struct ResolutionResult {
  std::optional<RoutingRecord> record;
  std::optional<RoutingErrorCode> no_order_reason;
  [[nodiscard]] bool order_allowed() const noexcept { return record.has_value(); }
};

class InstrumentResolver {
 public:
  [[nodiscard]] static InstrumentResolver load(const std::filesystem::path& snapshot_path,
                                               const std::filesystem::path& manifest_path,
                                               std::string_view expected_trading_date);
  [[nodiscard]] ResolutionResult resolve(std::string_view canonical_instrument_id) const;
  [[nodiscard]] ResolutionResult resolve_token(std::string_view instrument_token) const;
  [[nodiscard]] const std::string& snapshot_digest() const noexcept;

 private:
  std::string digest_;
  std::unordered_map<std::string, RoutingRecord> by_canonical_;
  std::unordered_map<std::string, RoutingRecord> by_token_;
};

}  // namespace shaurya::execution
