cmake_minimum_required(VERSION 3.20)
project(shaurya_execution VERSION 0.1.0 LANGUAGES CXX)

include(cmake/ShauryaBuildOptions.cmake)
include(cmake/ShauryaWarnings.cmake)

option(SHAURYA_ENABLE_KOTAK_LIVE "Compile a network-capable Kotak transport" OFF)
if(SHAURYA_ENABLE_KOTAK_LIVE)
  message(FATAL_ERROR
    "KOTAK LIVE REFUSED: this delivery contains fixture codecs only; "
    "SHAURYA_ENABLE_KOTAK_LIVE must remain OFF"
  )
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(SHAURYA_SOURCE_REVISION "unknown" CACHE STRING "Source revision for non-secret attestation")
set(SHAURYA_REQUESTED_SOURCE_REVISION "${SHAURYA_SOURCE_REVISION}")
find_package(Git QUIET)
if(NOT GIT_FOUND)
  message(FATAL_ERROR "verifiable Git repository metadata is required for source attestation")
endif()
execute_process(
  COMMAND "${GIT_EXECUTABLE}" rev-parse --verify HEAD
  WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
  RESULT_VARIABLE SHAURYA_GIT_REVISION_RESULT
  OUTPUT_VARIABLE SHAURYA_GIT_REVISION
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)
string(LENGTH "${SHAURYA_GIT_REVISION}" SHAURYA_GIT_REVISION_LENGTH)
if(NOT SHAURYA_GIT_REVISION_RESULT EQUAL 0 OR
    NOT SHAURYA_GIT_REVISION_LENGTH EQUAL 40 OR
    NOT SHAURYA_GIT_REVISION MATCHES "^[0-9a-f]+$")
  message(FATAL_ERROR "verifiable Git HEAD is required for source attestation")
endif()
if(NOT SHAURYA_REQUESTED_SOURCE_REVISION STREQUAL "unknown" AND
    NOT SHAURYA_REQUESTED_SOURCE_REVISION STREQUAL SHAURYA_GIT_REVISION)
  message(FATAL_ERROR "SHAURYA_SOURCE_REVISION override does not match verified Git HEAD")
endif()
set(SHAURYA_SOURCE_REVISION "${SHAURYA_GIT_REVISION}")
if(NOT CMAKE_BUILD_TYPE MATCHES "^(|Debug|Release|RelWithDebInfo|MinSizeRel)$")
  message(FATAL_ERROR "CMAKE_BUILD_TYPE is not an attestation-safe supported value")
endif()
set(SHAURYA_GENERATED_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${SHAURYA_GENERATED_DIR}")
set(SHAURYA_ATTESTATION_SOURCE
    "${SHAURYA_GENERATED_DIR}/build_attestation_values.cpp")
set(SHAURYA_ATTESTATION_STAMP "${CMAKE_CURRENT_BINARY_DIR}/source-attestation.stamp")
set(SHAURYA_ATTESTATION_FORCE "${CMAKE_CURRENT_BINARY_DIR}/source-attestation.force")
add_custom_command(
  OUTPUT "${SHAURYA_ATTESTATION_FORCE}"
  COMMAND "${CMAKE_COMMAND}" -E touch "${SHAURYA_ATTESTATION_FORCE}"
  VERBATIM)
set_source_files_properties("${SHAURYA_ATTESTATION_FORCE}" PROPERTIES SYMBOLIC TRUE)
set(SHAURYA_ATTESTATION_COMMAND
  "${CMAKE_COMMAND}"
  "-DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}"
  "-DOUTPUT_FILE=${SHAURYA_ATTESTATION_SOURCE}"
  "-DSTAMP_FILE=${SHAURYA_ATTESTATION_STAMP}"
  "-DTEMPLATE_FILE=${CMAKE_CURRENT_SOURCE_DIR}/include/shaurya/execution/build_attestation.hpp.in"
  "-DREQUESTED_REVISION=${SHAURYA_REQUESTED_SOURCE_REVISION}"
  "-DPROJECT_VERSION_VALUE=${PROJECT_VERSION}"
  "-DCOMPILER_ID_VALUE=${CMAKE_CXX_COMPILER_ID}"
  "-DBUILD_TYPE_VALUE=${CMAKE_BUILD_TYPE}"
  "-DLIVE_ROUTER_VALUE=${SHAURYA_LIVE_ROUTER_ATTESTATION}"
  "-DGIT_EXECUTABLE_VALUE=${GIT_EXECUTABLE}"
  -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ShauryaSourceAttestation.cmake")
execute_process(COMMAND ${SHAURYA_ATTESTATION_COMMAND} RESULT_VARIABLE SHAURYA_ATTESTATION_RESULT)
if(NOT SHAURYA_ATTESTATION_RESULT EQUAL 0)
  message(FATAL_ERROR "source attestation generation failed")
endif()
add_custom_command(
  OUTPUT "${SHAURYA_ATTESTATION_SOURCE}" "${SHAURYA_ATTESTATION_STAMP}"
  COMMAND ${SHAURYA_ATTESTATION_COMMAND}
  DEPENDS "${SHAURYA_ATTESTATION_FORCE}"
          "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ShauryaSourceAttestation.cmake"
          "${CMAKE_CURRENT_SOURCE_DIR}/include/shaurya/execution/build_attestation.hpp.in"
  VERBATIM)
set_source_files_properties("${SHAURYA_ATTESTATION_SOURCE}" "${SHAURYA_ATTESTATION_STAMP}"
  PROPERTIES GENERATED TRUE SYMBOLIC TRUE)
set_property(SOURCE "${SHAURYA_ATTESTATION_SOURCE}" APPEND PROPERTY
             OBJECT_DEPENDS "${SHAURYA_ATTESTATION_FORCE}")

function(shaurya_require_fresh_attestation target)
  if(NOT TARGET "${target}")
    message(FATAL_ERROR "attestation consumer target does not exist: ${target}")
  endif()
  string(MAKE_C_IDENTIFIER "${target}" safe_target)
  set(link_force "${CMAKE_CURRENT_BINARY_DIR}/${safe_target}-attestation-link.force")
  set(link_anchor "${CMAKE_CURRENT_BINARY_DIR}/${safe_target}-attestation-link-anchor.cpp")
  file(WRITE "${link_anchor}"
    "namespace { [[maybe_unused]] constexpr int kAttestationLinkAnchor_${safe_target} = 0; }\n")
  add_custom_command(
    OUTPUT "${link_force}"
    COMMAND "${CMAKE_COMMAND}" -E touch "${link_force}"
    VERBATIM)
  add_custom_command(
    OUTPUT "${link_anchor}"
    COMMAND "${CMAKE_COMMAND}" -E touch "${link_anchor}"
    DEPENDS "${link_force}"
    VERBATIM)
  set_source_files_properties("${link_force}" PROPERTIES
    GENERATED TRUE SYMBOLIC TRUE HEADER_FILE_ONLY TRUE)
  set_source_files_properties("${link_anchor}" PROPERTIES GENERATED TRUE SYMBOLIC TRUE)
  set_property(SOURCE "${link_anchor}" APPEND PROPERTY OBJECT_DEPENDS "${link_force}")
  target_sources("${target}" PRIVATE "${link_force}" "${link_anchor}")
  # Owning the symbolic prerequisite in the consumer's generated build graph makes the final
  # archive/link causal even on filesystems with coarse timestamp granularity.
  set_property(TARGET "${target}" APPEND PROPERTY LINK_DEPENDS "${link_force}")
endfunction()

add_library(shaurya_execution_build STATIC
  src/build_attestation.cpp
  "${SHAURYA_ATTESTATION_SOURCE}"
)
target_include_directories(shaurya_execution_build PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
shaurya_require_fresh_attestation(shaurya_execution_build)
set_property(TARGET shaurya_execution_build APPEND PROPERTY
             INTERFACE_LINK_DEPENDS "${SHAURYA_ATTESTATION_FORCE}")
shaurya_apply_warnings(shaurya_execution_build)

add_library(shaurya_execution_contracts STATIC
  src/canonical_json.cpp
  src/contracts.cpp
  src/routing_snapshot.cpp
  src/instrument_resolver.cpp
)
target_include_directories(shaurya_execution_contracts PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
shaurya_apply_warnings(shaurya_execution_contracts)

add_library(shaurya_execution_core STATIC
  src/order_state_machine.cpp
  src/execution_ledger.cpp
  src/reconstructed_state.cpp
  src/ledger_replay.cpp
  src/idempotency_store.cpp
  src/ledger_repair.cpp
)
target_include_directories(shaurya_execution_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(shaurya_execution_core PUBLIC shaurya_execution_contracts)
shaurya_apply_warnings(shaurya_execution_core)

add_library(shaurya_execution_controls STATIC
  src/risk.cpp
  src/paper_broker.cpp
  src/kotak_adapter.cpp
  src/reconciliation.cpp
  src/execution_session.cpp
)
target_include_directories(shaurya_execution_controls PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(shaurya_execution_controls PUBLIC shaurya_execution_core)
target_compile_definitions(shaurya_execution_controls PUBLIC SHAURYA_ENABLE_KOTAK_LIVE=0)
shaurya_apply_warnings(shaurya_execution_controls)

add_library(shaurya_execution_ipc STATIC
  src/ipc_transport.cpp
  src/peer_identity.cpp
  src/ipc_protocol.cpp
  src/executor.cpp
)
target_include_directories(shaurya_execution_ipc PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(shaurya_execution_ipc PUBLIC
  shaurya_execution_build
  shaurya_execution_controls
)
target_compile_definitions(shaurya_execution_ipc PUBLIC SHAURYA_ENABLE_KOTAK_LIVE=0)
shaurya_apply_warnings(shaurya_execution_ipc)

add_executable(shaurya-executor src/main.cpp)
target_link_libraries(shaurya-executor PRIVATE shaurya_execution_ipc)
shaurya_require_fresh_attestation(shaurya-executor)
shaurya_apply_warnings(shaurya-executor)
install(TARGETS shaurya-executor RUNTIME DESTINATION bin)

add_executable(shaurya-ledger-repair tools/ledger_repair.cpp)
target_link_libraries(shaurya-ledger-repair PRIVATE shaurya_execution_core)
shaurya_apply_warnings(shaurya-ledger-repair)

include(CTest)
if(BUILD_TESTING)
  add_subdirectory(tests)
endif()
