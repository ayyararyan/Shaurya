cmake_minimum_required(VERSION 3.20)
project(shaurya_execution VERSION 0.1.0 LANGUAGES CXX)

include(cmake/ShauryaBuildOptions.cmake)
include(cmake/ShauryaWarnings.cmake)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(SHAURYA_SOURCE_REVISION "unknown" CACHE STRING "Source revision for non-secret attestation")
if(NOT SHAURYA_SOURCE_REVISION STREQUAL "unknown")
  string(LENGTH "${SHAURYA_SOURCE_REVISION}" SHAURYA_SOURCE_REVISION_LENGTH)
  if(NOT SHAURYA_SOURCE_REVISION_LENGTH EQUAL 40 OR
      NOT SHAURYA_SOURCE_REVISION MATCHES "^[0-9a-f]+$")
    message(FATAL_ERROR "SHAURYA_SOURCE_REVISION must be 'unknown' or 40 lowercase hex characters")
  endif()
endif()
if(NOT CMAKE_BUILD_TYPE MATCHES "^(|Debug|Release|RelWithDebInfo|MinSizeRel)$")
  message(FATAL_ERROR "CMAKE_BUILD_TYPE is not an attestation-safe supported value")
endif()
set(SHAURYA_GENERATED_INCLUDE_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${SHAURYA_GENERATED_INCLUDE_DIR}/shaurya/execution")
configure_file(
  include/shaurya/execution/build_attestation.hpp.in
  "${SHAURYA_GENERATED_INCLUDE_DIR}/shaurya/execution/build_attestation.hpp"
  @ONLY
)

add_library(shaurya_execution_build STATIC src/build_attestation.cpp)
target_include_directories(shaurya_execution_build PUBLIC "${SHAURYA_GENERATED_INCLUDE_DIR}")
shaurya_apply_warnings(shaurya_execution_build)

add_library(shaurya_execution_contracts STATIC
  src/canonical_json.cpp
  src/contracts.cpp
  src/routing_snapshot.cpp
  src/instrument_resolver.cpp
)
target_include_directories(shaurya_execution_contracts PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
shaurya_apply_warnings(shaurya_execution_contracts)

include(CTest)
if(BUILD_TESTING)
  add_subdirectory(tests)
endif()
