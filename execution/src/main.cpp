#include "shaurya/execution/executor.hpp"

#include <iostream>
#include <string>
#include <vector>

int main(int argc, char** argv) {
  std::vector<std::string> arguments;
  for (int index = 1; index < argc; ++index) arguments.emplace_back(argv[index]);
  return shaurya::execution::executor_cli(arguments, std::cout, std::cerr);
}
