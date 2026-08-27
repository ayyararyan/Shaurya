#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

namespace shaurya::execution {

class JsonError : public std::runtime_error {
 public:
  explicit JsonError(std::string code, bool incomplete = false);
  [[nodiscard]] const std::string& code() const noexcept;
  [[nodiscard]] bool incomplete() const noexcept;

 private:
  std::string code_;
  bool incomplete_{};
};

struct JsonInteger {
  std::string digits;
  friend bool operator==(const JsonInteger&, const JsonInteger&) = default;
};

struct JsonValue;
using JsonArray = std::vector<JsonValue>;
using JsonObject = std::map<std::string, JsonValue, std::less<>>;

struct JsonValue {
  using Storage =
      std::variant<std::nullptr_t, bool, JsonInteger, std::string, JsonArray, JsonObject>;
  Storage value;

  JsonValue();
  explicit JsonValue(bool item);
  explicit JsonValue(JsonInteger item);
  explicit JsonValue(std::string item);
  explicit JsonValue(JsonArray item);
  explicit JsonValue(JsonObject item);
  friend bool operator==(const JsonValue&, const JsonValue&) = default;
};

inline constexpr std::size_t kMaximumJsonBytes = 1U << 20U;
inline constexpr std::size_t kMaximumJsonDepth = 32U;
inline constexpr std::size_t kMaximumJsonMembers = 4096U;

[[nodiscard]] JsonValue parse_json(std::string_view input,
                                   std::size_t maximum_bytes = kMaximumJsonBytes);
[[nodiscard]] std::string canonical_json(const JsonValue& value);
[[nodiscard]] std::string sha256_hex(std::string_view bytes);
[[nodiscard]] std::int64_t json_int64(const JsonValue& value, std::string_view field);
[[nodiscard]] std::uint64_t json_uint64(const JsonValue& value, std::string_view field);
[[nodiscard]] const JsonObject& json_object(const JsonValue& value, std::string_view field);
[[nodiscard]] const JsonArray& json_array(const JsonValue& value, std::string_view field);
[[nodiscard]] const std::string& json_string(const JsonValue& value, std::string_view field);
[[nodiscard]] bool json_bool(const JsonValue& value, std::string_view field);

}  // namespace shaurya::execution
