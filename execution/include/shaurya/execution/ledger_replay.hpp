#pragma once

#include "shaurya/execution/execution_ledger.hpp"
#include "shaurya/execution/reconstructed_state.hpp"

namespace shaurya::execution {
[[nodiscard]] ReconstructedState replay_ledger(const LedgerVerificationResult& verification);
[[nodiscard]] ReconstructedState replay_ledger(const std::filesystem::path& path);
}  // namespace shaurya::execution
