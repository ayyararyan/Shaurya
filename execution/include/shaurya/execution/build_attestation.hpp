#pragma once

#include <string>

namespace shaurya::execution {
extern const char kProjectVersion[];
extern const char kSourceRevision[];
extern const char kSourceState[];
extern const char kSourceTreeDigest[];
extern const char kCompilerId[];
extern const char kBuildType[];
extern const char kLiveRouter[];

[[nodiscard]] std::string build_attestation();
}  // namespace shaurya::execution
