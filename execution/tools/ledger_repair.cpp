#include "shaurya/execution/ledger_repair.hpp"

#include "shaurya/execution/execution_ledger.hpp"

#include <charconv>
#include <iostream>
#include <string_view>

namespace {
void usage() {
  std::cerr << "usage: shaurya-ledger-repair INPUT OUTPUT ACTIVE_SEGMENT CONFIRMATION "
               "SESSION_UUID EVENT_UUID TIMESTAMP_NS\n";
}
}  // namespace

int main(int argc, char** argv) {
  if (argc != 8) {
    usage();
    return 64;
  }
  std::int64_t timestamp{};
  const std::string_view timestamp_text(argv[7]);
  const auto parsed = std::from_chars(timestamp_text.data(),
                                      timestamp_text.data() + timestamp_text.size(), timestamp);
  if (parsed.ec != std::errc{} || parsed.ptr != timestamp_text.data() + timestamp_text.size()) {
    usage();
    return 64;
  }
  try {
    const auto result = shaurya::execution::repair_truncated_ledger(
        {argv[1], argv[2], argv[4], argv[5], argv[6], timestamp, argv[3]});
    std::cout << "copied_records=" << result.copied_records
              << " verified_prefix_bytes=" << result.verified_prefix_bytes
              << " damaged_sha256=" << result.damaged_sha256 << '\n';
    return 0;
  } catch (const shaurya::execution::LedgerError& error) {
    std::cerr << error.code() << '\n';
    return 1;
  }
}
