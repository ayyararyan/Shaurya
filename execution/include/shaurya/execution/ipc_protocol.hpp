#pragma once

#include "shaurya/execution/contracts.hpp"
#include "shaurya/execution/peer_identity.hpp"

#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace shaurya::execution {

enum class IpcMessageKind {
  MarketObservation,
  StrategyBookObservation,
  OrderIntent,
  EventAcknowledgement,
  ExecutionEvent
};

struct StrategyBookLevel {
  std::uint64_t price_paise{};
  std::uint64_t quantity{};
  std::uint32_t order_count{};
  friend bool operator==(const StrategyBookLevel&, const StrategyBookLevel&) = default;
};

struct StrategyBookObservation {
  std::string canonical_instrument_id;
  std::vector<StrategyBookLevel> bids;
  std::vector<StrategyBookLevel> asks;
  std::optional<std::uint64_t> last_trade_paise;
  std::uint64_t cumulative_volume{};
  std::uint64_t last_trade_quantity{};
  std::uint64_t open_interest{};
  std::optional<std::int64_t> exchange_timestamp_ns;
  std::int64_t receive_timestamp_ns{};
  std::string source;
  std::string provenance;
  std::vector<std::string> quality_flags;

  [[nodiscard]] static StrategyBookObservation parse(std::string_view json);
  [[nodiscard]] std::string to_json() const;
  [[nodiscard]] MarketObservation derive_market_observation() const;
  friend bool operator==(const StrategyBookObservation&, const StrategyBookObservation&) = default;
};

struct IpcHandshake {
  PeerHandshakeBindings bindings;
  std::optional<std::uint64_t> after_event_sequence;
  std::optional<std::string> strategy_id;
};

struct IpcEnvelope {
  IpcMessageKind kind{IpcMessageKind::MarketObservation};
  std::string execution_session_id;
  std::optional<std::string> strategy_id;
  std::optional<std::uint64_t> source_sequence;
  std::optional<std::uint64_t> event_sequence;
  std::string canonical_payload;
  std::optional<std::string> source_digest;
};

struct EventAcknowledgement {
  std::uint64_t acknowledged_event_sequence{};
  [[nodiscard]] static EventAcknowledgement parse(std::string_view json);
  [[nodiscard]] std::string to_json() const;
  friend bool operator==(const EventAcknowledgement&, const EventAcknowledgement&) = default;
};

class IpcProtocolError : public std::runtime_error {
 public:
  explicit IpcProtocolError(std::string code);
  [[nodiscard]] const std::string& code() const noexcept { return code_; }
 private:
  std::string code_;
};

[[nodiscard]] IpcHandshake parse_ipc_handshake(std::string_view bytes);
[[nodiscard]] IpcEnvelope parse_ipc_envelope(std::string_view bytes);
[[nodiscard]] std::string encode_ipc_envelope(const IpcEnvelope& envelope);
void authorize_inbound(PeerRole role, const IpcEnvelope& envelope,
                       std::string_view expected_session,
                       std::string_view expected_strategy);

struct ReplayEvent {
  std::uint64_t sequence{};
  std::string execution_session_id;
  std::string strategy_id;
  std::string canonical_event;
};

class EventReplayLog {
 public:
  void append(ReplayEvent event);
  [[nodiscard]] std::vector<ReplayEvent> replay_after(
      std::uint64_t after_sequence, std::string_view execution_session_id,
      std::string_view strategy_id) const;
  [[nodiscard]] std::uint64_t last_sequence() const noexcept;
 private:
  std::vector<ReplayEvent> events_;
};

}  // namespace shaurya::execution
