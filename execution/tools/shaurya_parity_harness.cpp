#include "shaurya/execution/parity_harness.hpp"

#include <iostream>
#include <string>
#include <vector>

int main(int argc, char** argv) {
  std::vector<std::string> arguments;
  arguments.reserve(static_cast<std::size_t>(argc > 0 ? argc - 1 : 0));
  for (int index = 1; index < argc; ++index) arguments.emplace_back(argv[index]);
  return shaurya::execution::parity_harness_cli(arguments, std::cout, std::cerr);
}
