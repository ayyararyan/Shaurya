#include "shaurya/execution/canonical_json.hpp"

#include <array>
#include <bit>
#include <charconv>
#include <utility>

namespace shaurya::execution {
namespace {

[[noreturn]] void fail(std::string code) { throw JsonError(std::move(code)); }

bool valid_utf8(std::string_view value) {
  std::size_t index = 0;
  while (index < value.size()) {
    const auto first = static_cast<unsigned char>(value[index]);
    if (first < 0x80U) { ++index; continue; }
    std::size_t count = 0;
    std::uint32_t codepoint = 0;
    if ((first & 0xE0U) == 0xC0U) { count = 2; codepoint = first & 0x1FU; }
    else if ((first & 0xF0U) == 0xE0U) { count = 3; codepoint = first & 0x0FU; }
    else if ((first & 0xF8U) == 0xF0U) { count = 4; codepoint = first & 0x07U; }
    else return false;
    if (index + count > value.size()) return false;
    for (std::size_t offset = 1; offset < count; ++offset) {
      const auto byte = static_cast<unsigned char>(value[index + offset]);
      if ((byte & 0xC0U) != 0x80U) return false;
      codepoint = (codepoint << 6U) | (byte & 0x3FU);
    }
    if ((count == 2 && codepoint < 0x80U) || (count == 3 && codepoint < 0x800U) ||
        (count == 4 && codepoint < 0x10000U) || codepoint > 0x10FFFFU ||
        (codepoint >= 0xD800U && codepoint <= 0xDFFFU)) return false;
    index += count;
  }
  return true;
}

void append_utf8(std::string& output, std::uint32_t point) {
  if (point <= 0x7FU) output.push_back(static_cast<char>(point));
  else if (point <= 0x7FFU) {
    output.push_back(static_cast<char>(0xC0U | (point >> 6U)));
    output.push_back(static_cast<char>(0x80U | (point & 0x3FU)));
  } else if (point <= 0xFFFFU) {
    output.push_back(static_cast<char>(0xE0U | (point >> 12U)));
    output.push_back(static_cast<char>(0x80U | ((point >> 6U) & 0x3FU)));
    output.push_back(static_cast<char>(0x80U | (point & 0x3FU)));
  } else {
    output.push_back(static_cast<char>(0xF0U | (point >> 18U)));
    output.push_back(static_cast<char>(0x80U | ((point >> 12U) & 0x3FU)));
    output.push_back(static_cast<char>(0x80U | ((point >> 6U) & 0x3FU)));
    output.push_back(static_cast<char>(0x80U | (point & 0x3FU)));
  }
}

class Parser {
 public:
  explicit Parser(std::string_view input) : input_(input) {}
  JsonValue parse() {
    space();
    JsonValue result = value(0);
    space();
    if (position_ != input_.size()) fail("trailing_data");
    return result;
  }

 private:
  void space() {
    while (position_ < input_.size() &&
           (input_[position_] == ' ' || input_[position_] == '\n' ||
            input_[position_] == '\r' || input_[position_] == '\t')) ++position_;
  }
  bool consume(char wanted) {
    if (position_ < input_.size() && input_[position_] == wanted) { ++position_; return true; }
    return false;
  }
  void literal(std::string_view expected) {
    if (input_.substr(position_, expected.size()) != expected) fail("invalid_json");
    position_ += expected.size();
  }
  static std::uint32_t hex(char value) {
    if (value >= '0' && value <= '9') return static_cast<std::uint32_t>(value - '0');
    if (value >= 'a' && value <= 'f') return static_cast<std::uint32_t>(value - 'a' + 10);
    if (value >= 'A' && value <= 'F') return static_cast<std::uint32_t>(value - 'A' + 10);
    fail("invalid_unicode_escape");
  }
  std::uint32_t code_unit() {
    if (position_ + 4 > input_.size()) fail("invalid_unicode_escape");
    std::uint32_t result = 0;
    for (int index = 0; index < 4; ++index) result = (result << 4U) | hex(input_[position_++]);
    return result;
  }
  std::string string() {
    if (!consume('"')) fail("string_required");
    std::string output;
    while (position_ < input_.size()) {
      const char item = input_[position_++];
      if (item == '"') return output;
      if (static_cast<unsigned char>(item) < 0x20U) fail("invalid_control_character");
      if (item != '\\') { output.push_back(item); continue; }
      if (position_ == input_.size()) fail("invalid_escape");
      const char escaped = input_[position_++];
      switch (escaped) {
        case '"': output.push_back('"'); break;
        case '\\': output.push_back('\\'); break;
        case '/': output.push_back('/'); break;
        case 'b': output.push_back('\b'); break;
        case 'f': output.push_back('\f'); break;
        case 'n': output.push_back('\n'); break;
        case 'r': output.push_back('\r'); break;
        case 't': output.push_back('\t'); break;
        case 'u': {
          std::uint32_t point = code_unit();
          if (point >= 0xD800U && point <= 0xDBFFU) {
            if (position_ + 2 > input_.size() || input_[position_] != '\\' ||
                input_[position_ + 1] != 'u') fail("invalid_unicode_surrogate");
            position_ += 2;
            const std::uint32_t low = code_unit();
            if (low < 0xDC00U || low > 0xDFFFU) fail("invalid_unicode_surrogate");
            point = 0x10000U + ((point - 0xD800U) << 10U) + (low - 0xDC00U);
          } else if (point >= 0xDC00U && point <= 0xDFFFU) fail("invalid_unicode_surrogate");
          append_utf8(output, point);
          break;
        }
        default: fail("invalid_escape");
      }
    }
    fail("unterminated_string");
  }
  JsonValue integer() {
    const std::size_t start = position_;
    consume('-');
    if (position_ == input_.size() || input_[position_] < '0' || input_[position_] > '9')
      fail("integer_required");
    if (input_[position_] == '0') {
      ++position_;
      if (position_ < input_.size() && input_[position_] >= '0' && input_[position_] <= '9')
        fail("invalid_integer");
    } else {
      while (position_ < input_.size() && input_[position_] >= '0' && input_[position_] <= '9')
        ++position_;
    }
    if (position_ < input_.size() &&
        (input_[position_] == '.' || input_[position_] == 'e' || input_[position_] == 'E'))
      fail("integer_required");
    std::string digits(input_.substr(start, position_ - start));
    if (digits == "-0") digits = "0";
    return JsonValue(JsonInteger{std::move(digits)});
  }
  JsonValue array(std::size_t depth) {
    consume('[');
    JsonArray output;
    space();
    if (consume(']')) return JsonValue(std::move(output));
    while (true) {
      if (++members_ > kMaximumJsonMembers) fail("too_many_members");
      output.push_back(value(depth + 1));
      space();
      if (consume(']')) break;
      if (!consume(',')) fail("invalid_json");
      space();
    }
    return JsonValue(std::move(output));
  }
  JsonValue object(std::size_t depth) {
    consume('{');
    JsonObject output;
    space();
    if (consume('}')) return JsonValue(std::move(output));
    while (true) {
      if (++members_ > kMaximumJsonMembers) fail("too_many_members");
      std::string key = string();
      space();
      if (!consume(':')) fail("invalid_json");
      space();
      auto [unused, inserted] = output.emplace(std::move(key), value(depth + 1));
      (void)unused;
      if (!inserted) fail("duplicate_field");
      space();
      if (consume('}')) break;
      if (!consume(',')) fail("invalid_json");
      space();
    }
    return JsonValue(std::move(output));
  }
  JsonValue value(std::size_t depth) {
    if (depth > kMaximumJsonDepth) fail("maximum_depth");
    space();
    if (position_ == input_.size()) fail("invalid_json");
    switch (input_[position_]) {
      case '{': return object(depth);
      case '[': return array(depth);
      case '"': return JsonValue(string());
      case 't': literal("true"); return JsonValue(true);
      case 'f': literal("false"); return JsonValue(false);
      case 'n': literal("null"); return JsonValue();
      default: return integer();
    }
  }
  std::string_view input_;
  std::size_t position_{0};
  std::size_t members_{0};
};

void encode_string(std::string_view value, std::string& output) {
  output.push_back('"');
  constexpr char hex[] = "0123456789abcdef";
  for (const char raw_item : value) {
    const auto item = static_cast<unsigned char>(raw_item);
    switch (item) {
      case '"': output += "\\\""; break;
      case '\\': output += "\\\\"; break;
      case '\b': output += "\\b"; break;
      case '\f': output += "\\f"; break;
      case '\n': output += "\\n"; break;
      case '\r': output += "\\r"; break;
      case '\t': output += "\\t"; break;
      default:
        if (item < 0x20U) {
          output += "\\u00";
          output.push_back(hex[item >> 4U]);
          output.push_back(hex[item & 0x0FU]);
        } else output.push_back(static_cast<char>(item));
    }
  }
  output.push_back('"');
}
void encode(const JsonValue& value, std::string& output) {
  if (std::holds_alternative<std::nullptr_t>(value.value)) output += "null";
  else if (const auto* boolean = std::get_if<bool>(&value.value)) output += *boolean ? "true" : "false";
  else if (const auto* number = std::get_if<JsonInteger>(&value.value)) output += number->digits;
  else if (const auto* string = std::get_if<std::string>(&value.value)) encode_string(*string, output);
  else if (const auto* items = std::get_if<JsonArray>(&value.value)) {
    output.push_back('[');
    for (std::size_t index = 0; index < items->size(); ++index) {
      if (index != 0) output.push_back(',');
      encode((*items)[index], output);
    }
    output.push_back(']');
  } else {
    output.push_back('{');
    bool first = true;
    for (const auto& [key, member] : std::get<JsonObject>(value.value)) {
      if (!first) output.push_back(',');
      first = false;
      encode_string(key, output);
      output.push_back(':');
      encode(member, output);
    }
    output.push_back('}');
  }
}

constexpr std::array<std::uint32_t, 64> kSha256Constants = {
    0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,
    0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,
    0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,
    0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,
    0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,
    0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,
    0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,
    0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U};

std::array<std::uint8_t, 32> sha256(std::string_view input) {
  std::vector<std::uint8_t> bytes(input.begin(), input.end());
  const std::uint64_t bit_size = static_cast<std::uint64_t>(bytes.size()) * 8U;
  bytes.push_back(0x80U);
  while ((bytes.size() % 64U) != 56U) bytes.push_back(0U);
  for (int shift = 56; shift >= 0; shift -= 8)
    bytes.push_back(static_cast<std::uint8_t>((bit_size >> static_cast<unsigned>(shift)) & 0xFFU));
  std::array<std::uint32_t, 8> hash = {0x6a09e667U,0xbb67ae85U,0x3c6ef372U,0xa54ff53aU,
                                       0x510e527fU,0x9b05688cU,0x1f83d9abU,0x5be0cd19U};
  for (std::size_t chunk = 0; chunk < bytes.size(); chunk += 64U) {
    std::array<std::uint32_t, 64> words{};
    for (std::size_t index = 0; index < 16; ++index) {
      const std::size_t offset = chunk + index * 4U;
      words[index] = (static_cast<std::uint32_t>(bytes[offset]) << 24U) |
                     (static_cast<std::uint32_t>(bytes[offset+1]) << 16U) |
                     (static_cast<std::uint32_t>(bytes[offset+2]) << 8U) |
                     static_cast<std::uint32_t>(bytes[offset+3]);
    }
    for (std::size_t index = 16; index < 64; ++index) {
      const auto s0 = std::rotr(words[index-15],7) ^ std::rotr(words[index-15],18) ^ (words[index-15]>>3U);
      const auto s1 = std::rotr(words[index-2],17) ^ std::rotr(words[index-2],19) ^ (words[index-2]>>10U);
      words[index] = words[index-16] + s0 + words[index-7] + s1;
    }
    auto a=hash[0], b=hash[1], c=hash[2], d=hash[3], e=hash[4], f=hash[5], g=hash[6], h=hash[7];
    for (std::size_t index = 0; index < 64; ++index) {
      const auto sum1=std::rotr(e,6)^std::rotr(e,11)^std::rotr(e,25);
      const auto choice=(e&f)^((~e)&g);
      const auto t1=h+sum1+choice+kSha256Constants[index]+words[index];
      const auto sum0=std::rotr(a,2)^std::rotr(a,13)^std::rotr(a,22);
      const auto majority=(a&b)^(a&c)^(b&c);
      const auto t2=sum0+majority;
      h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
    }
    hash[0]+=a; hash[1]+=b; hash[2]+=c; hash[3]+=d; hash[4]+=e; hash[5]+=f; hash[6]+=g; hash[7]+=h;
  }
  std::array<std::uint8_t,32> output{};
  for (std::size_t index=0; index<hash.size(); ++index) {
    output[index*4U]=static_cast<std::uint8_t>(hash[index]>>24U);
    output[index*4U+1U]=static_cast<std::uint8_t>(hash[index]>>16U);
    output[index*4U+2U]=static_cast<std::uint8_t>(hash[index]>>8U);
    output[index*4U+3U]=static_cast<std::uint8_t>(hash[index]);
  }
  return output;
}
}  // namespace

JsonError::JsonError(std::string code) : std::runtime_error(code), code_(std::move(code)) {}
const std::string& JsonError::code() const noexcept { return code_; }
JsonValue::JsonValue() : value(nullptr) {}
JsonValue::JsonValue(bool item) : value(item) {}
JsonValue::JsonValue(JsonInteger item) : value(std::move(item)) {}
JsonValue::JsonValue(std::string item) : value(std::move(item)) {}
JsonValue::JsonValue(JsonArray item) : value(std::move(item)) {}
JsonValue::JsonValue(JsonObject item) : value(std::move(item)) {}
JsonValue parse_json(std::string_view input, std::size_t maximum_bytes) {
  if (input.size() > maximum_bytes) fail("packet_too_large");
  if (!valid_utf8(input)) fail("invalid_utf8");
  return Parser(input).parse();
}
std::string canonical_json(const JsonValue& value) { std::string output; encode(value, output); return output; }
std::string sha256_hex(std::string_view bytes) {
  constexpr char hex[]="0123456789abcdef";
  std::string output; output.reserve(64);
  for (const auto byte : sha256(bytes)) { output.push_back(hex[byte>>4U]); output.push_back(hex[byte&0x0FU]); }
  return output;
}
std::int64_t json_int64(const JsonValue& value, std::string_view) {
  const auto* integer=std::get_if<JsonInteger>(&value.value); if (!integer) fail("integer_required");
  std::int64_t output=0; const auto [end,error]=std::from_chars(integer->digits.data(),integer->digits.data()+integer->digits.size(),output);
  if (error!=std::errc{} || end!=integer->digits.data()+integer->digits.size()) fail("integer_overflow"); return output;
}
std::uint64_t json_uint64(const JsonValue& value, std::string_view) {
  const auto* integer=std::get_if<JsonInteger>(&value.value);
  if (!integer || (!integer->digits.empty() && integer->digits.front()=='-')) fail("unsigned_integer_required");
  std::uint64_t output=0; const auto [end,error]=std::from_chars(integer->digits.data(),integer->digits.data()+integer->digits.size(),output);
  if (error!=std::errc{} || end!=integer->digits.data()+integer->digits.size()) fail("integer_overflow"); return output;
}
const JsonObject& json_object(const JsonValue& value, std::string_view) { const auto* item=std::get_if<JsonObject>(&value.value); if(!item) fail("object_required"); return *item; }
const JsonArray& json_array(const JsonValue& value, std::string_view) { const auto* item=std::get_if<JsonArray>(&value.value); if(!item) fail("array_required"); return *item; }
const std::string& json_string(const JsonValue& value, std::string_view) { const auto* item=std::get_if<std::string>(&value.value); if(!item) fail("string_required"); return *item; }
bool json_bool(const JsonValue& value, std::string_view) { const auto* item=std::get_if<bool>(&value.value); if(!item) fail("boolean_required"); return *item; }
}  // namespace shaurya::execution
