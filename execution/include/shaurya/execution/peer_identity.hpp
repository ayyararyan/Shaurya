#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>

namespace shaurya::execution {

enum class PeerRole { MarketPublisher, StrategyClient };
enum class PeerPlatform { Linux, Darwin };

struct PeerEvidence {
  PeerPlatform platform{PeerPlatform::Linux};
  std::uint64_t uid{};
  std::uint64_t gid{};
  std::int64_t pid{};
  std::string process_start_identity;
  std::string executable_digest;
  bool executable_evidence_available{};
};

struct ExpectedPeerIdentity {
  PeerRole role{PeerRole::MarketPublisher};
  std::uint64_t uid{};
  std::uint64_t gid{};
  std::string executable_digest;
  std::string configuration_digest;
  std::string protocol_version{"1.0.0"};
  std::string execution_session_id;
};

struct PeerHandshakeBindings {
  PeerRole role{PeerRole::MarketPublisher};
  std::string protocol_version;
  std::string execution_session_id;
  std::string configuration_digest;
  std::string executable_digest;
  std::string process_start_identity;
  std::string nonce;
};

class PeerIdentityError : public std::runtime_error {
 public:
  explicit PeerIdentityError(std::string code);
  [[nodiscard]] const std::string& code() const noexcept { return code_; }
 private:
  std::string code_;
};

class PeerInspector {
 public:
  virtual ~PeerInspector() = default;
  [[nodiscard]] virtual PeerEvidence inspect(int accepted_socket) const = 0;
};

class InjectedPeerInspector final : public PeerInspector {
 public:
  explicit InjectedPeerInspector(PeerEvidence evidence) : evidence_(std::move(evidence)) {}
  [[nodiscard]] PeerEvidence inspect(int) const override { return evidence_; }
  void replace(PeerEvidence evidence) { evidence_ = std::move(evidence); }
 private:
  PeerEvidence evidence_;
};

class SystemPeerInspector final : public PeerInspector {
 public:
  [[nodiscard]] PeerEvidence inspect(int accepted_socket) const override;
};

void validate_peer_identity(const ExpectedPeerIdentity& expected,
                            const PeerHandshakeBindings& handshake,
                            const PeerEvidence& evidence, bool production_required = true);
void validate_peer_continuity(const PeerEvidence& authenticated,
                              const PeerEvidence& current);
[[nodiscard]] bool constant_time_equal(std::string_view left, std::string_view right) noexcept;

}  // namespace shaurya::execution
