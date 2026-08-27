#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace shaurya::execution {

inline constexpr std::size_t kMaximumIpcPayloadBytes = 65'536U;

enum class IpcSocketMode { SeqPacket, Stream };
using IpcDeadline = std::chrono::steady_clock::time_point;

class IpcError : public std::runtime_error {
 public:
  explicit IpcError(std::string code);
  [[nodiscard]] const std::string& code() const noexcept { return code_; }
 private:
  std::string code_;
};

class IpcFrameCodec {
 public:
  explicit IpcFrameCodec(std::size_t maximum_payload_bytes = kMaximumIpcPayloadBytes);
  [[nodiscard]] std::vector<std::uint8_t> encode_stream(std::string_view payload) const;
  [[nodiscard]] std::string decode_stream(std::string_view frame) const;
  [[nodiscard]] std::string decode_packet(std::string_view packet, bool truncated) const;
  [[nodiscard]] std::size_t maximum_payload_bytes() const noexcept { return maximum_; }
 private:
  std::size_t maximum_{};
};

[[nodiscard]] IpcSocketMode select_unix_mode(bool seqpacket_supported) noexcept;
[[nodiscard]] std::pair<int, int> create_unix_socketpair(IpcSocketMode mode);
[[nodiscard]] std::string read_ipc_frame(int descriptor, IpcSocketMode mode,
                                        const IpcFrameCodec& codec,
                                        std::chrono::milliseconds timeout);
[[nodiscard]] std::string read_ipc_frame_until(int descriptor, IpcSocketMode mode,
                                               const IpcFrameCodec& codec,
                                               IpcDeadline deadline);
void write_ipc_frame(int descriptor, IpcSocketMode mode, const IpcFrameCodec& codec,
                     std::string_view payload, std::chrono::milliseconds timeout);
void write_ipc_frame_until(int descriptor, IpcSocketMode mode, const IpcFrameCodec& codec,
                           std::string_view payload, IpcDeadline deadline);

class ProtectedUnixListener {
 public:
  [[nodiscard]] static ProtectedUnixListener create(const std::filesystem::path& runtime_directory,
                                                     std::string socket_basename,
                                                     IpcSocketMode mode);
  [[nodiscard]] static ProtectedUnixListener create_at(
      int runtime_directory_descriptor, const std::filesystem::path& display_runtime_directory,
      std::string socket_basename, IpcSocketMode mode);
  ProtectedUnixListener(ProtectedUnixListener&& other) noexcept;
  ProtectedUnixListener& operator=(ProtectedUnixListener&& other) noexcept;
  ProtectedUnixListener(const ProtectedUnixListener&) = delete;
  ProtectedUnixListener& operator=(const ProtectedUnixListener&) = delete;
  ~ProtectedUnixListener();

  [[nodiscard]] int descriptor() const noexcept { return descriptor_; }
  [[nodiscard]] const std::filesystem::path& path() const noexcept { return path_; }
  [[nodiscard]] int accept_one(std::chrono::milliseconds timeout) const;
  [[nodiscard]] int accept_one_until(IpcDeadline deadline) const;
  void close() noexcept;

 private:
  ProtectedUnixListener(int descriptor, std::filesystem::path path,
                        int parent_descriptor, std::string basename,
                        std::uint64_t device, std::uint64_t inode);
  int descriptor_{-1};
  std::filesystem::path path_;
  int parent_descriptor_{-1};
  std::string basename_;
  std::uint64_t device_{};
  std::uint64_t inode_{};
};

}  // namespace shaurya::execution
