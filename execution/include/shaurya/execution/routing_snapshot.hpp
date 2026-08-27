#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace shaurya::execution {

struct RoutingRecord {
  std::string canonical_instrument_id;
  std::string instrument_token;
  std::string exchange_segment;
  std::string trading_symbol;
  std::uint64_t lot_size{};
  std::uint64_t tick_size_paise{};
  friend bool operator==(const RoutingRecord&, const RoutingRecord&) = default;
};

struct RoutingSnapshot {
  std::string trading_date;
  std::string digest;
  std::vector<RoutingRecord> records;
};

}  // namespace shaurya::execution
