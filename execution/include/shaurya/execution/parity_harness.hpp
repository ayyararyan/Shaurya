#pragma once

#include <ostream>
#include <string>
#include <vector>

namespace shaurya::execution {

inline constexpr const char* kParityHarnessSchemaVersion = "1.0.0";

// Test-only, shadow-only parity entry point. Production code must not invoke this API.
int parity_harness_cli(const std::vector<std::string>& arguments,
                       std::ostream& output, std::ostream& error);

}  // namespace shaurya::execution
