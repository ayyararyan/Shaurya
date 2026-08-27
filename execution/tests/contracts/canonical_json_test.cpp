#include "shaurya/execution/canonical_json.hpp"

#include <iostream>

using namespace shaurya::execution;

int main() {
  int failures = 0;
  const auto expect = [&](bool condition, const char* message) {
    if (!condition) {
      std::cerr << message << '\n';
      ++failures;
    }
  };
  const auto value = parse_json(" { \"z\" : -0, \"a\" : [true,null,\"x\"] } ");
  expect(canonical_json(value) == "{\"a\":[true,null,\"x\"],\"z\":0}", "canonical order");
  expect(sha256_hex("abc") ==
             "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
         "sha256 vector");
  try {
    (void)parse_json("{\"a\":1,\"a\":2}");
    expect(false, "duplicate accepted");
  } catch (const JsonError& error) {
    expect(error.code() == "duplicate_field", "duplicate code");
  }
  try {
    (void)parse_json("{\"a\":1.0}");
    expect(false, "float accepted");
  } catch (const JsonError& error) {
    expect(error.code() == "integer_required", "float code");
  }
  return failures == 0 ? 0 : 1;
}
