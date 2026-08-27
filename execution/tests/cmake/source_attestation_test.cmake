find_program(git_executable git REQUIRED)
set(repo "${BINARY_ROOT}/source-attestation-repo")
set(build "${BINARY_ROOT}/source-attestation-build")
file(REMOVE_RECURSE "${repo}" "${build}")
file(MAKE_DIRECTORY "${repo}/cmake" "${repo}/include/shaurya/execution")
file(COPY "${SOURCE_DIR}/cmake/ShauryaSourceAttestation.cmake" DESTINATION "${repo}/cmake")
file(COPY "${SOURCE_DIR}/include/shaurya/execution/build_attestation.hpp.in"
     DESTINATION "${repo}/include/shaurya/execution")
file(COPY "${SOURCE_DIR}/include/shaurya/execution/build_attestation.hpp"
     DESTINATION "${repo}/include/shaurya/execution")
file(WRITE "${repo}/main.cpp" [=[
#include "shaurya/execution/build_attestation.hpp"
#include <iostream>
int main() {
  std::cout << shaurya::execution::kSourceRevision << '|'
            << shaurya::execution::kSourceState << '|'
            << shaurya::execution::kSourceTreeDigest << '\n';
}
]=])
file(WRITE "${repo}/payload.cpp" "int tracked_payload = 1;\n")
set(project_text [=[
cmake_minimum_required(VERSION 3.20)
project(attestation_probe VERSION 1.0.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
find_package(Git REQUIRED)
set(generated "${CMAKE_BINARY_DIR}/generated/build_attestation_values.cpp")
set(stamp "${CMAKE_BINARY_DIR}/source-attestation.stamp")
set(force "${CMAKE_BINARY_DIR}/source-attestation.force")
add_custom_command(OUTPUT "${force}" COMMAND "${CMAKE_COMMAND}" -E touch "${force}" VERBATIM)
set_source_files_properties("${force}" PROPERTIES SYMBOLIC TRUE)
file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/generated")
set(command "${CMAKE_COMMAND}"
  "-DSOURCE_DIR=${CMAKE_SOURCE_DIR}" "-DOUTPUT_FILE=${generated}"
  "-DSTAMP_FILE=${stamp}"
  "-DTEMPLATE_FILE=${CMAKE_SOURCE_DIR}/include/shaurya/execution/build_attestation.hpp.in"
  "-DREQUESTED_REVISION=unknown" "-DPROJECT_VERSION_VALUE=1.0.0"
  "-DCOMPILER_ID_VALUE=${CMAKE_CXX_COMPILER_ID}" "-DBUILD_TYPE_VALUE=test"
  "-DLIVE_ROUTER_VALUE=off" "-DGIT_EXECUTABLE_VALUE=${GIT_EXECUTABLE}"
  -P "${CMAKE_SOURCE_DIR}/cmake/ShauryaSourceAttestation.cmake")
execute_process(COMMAND ${command} RESULT_VARIABLE generated_result)
if(NOT generated_result EQUAL 0)
  message(FATAL_ERROR "initial attestation failed")
endif()
add_custom_command(OUTPUT "${generated}" "${stamp}" COMMAND ${command}
  DEPENDS "${force}" "${CMAKE_SOURCE_DIR}/cmake/ShauryaSourceAttestation.cmake"
  VERBATIM)
set_source_files_properties("${generated}" "${stamp}" PROPERTIES GENERATED TRUE SYMBOLIC TRUE)
set_property(SOURCE "${generated}" APPEND PROPERTY OBJECT_DEPENDS "${force}")
function(require_fresh_attestation target)
  set(link_force "${CMAKE_BINARY_DIR}/${target}-attestation-link.force")
  set(link_anchor "${CMAKE_BINARY_DIR}/${target}-attestation-link-anchor.cpp")
  file(WRITE "${link_anchor}"
    "namespace { [[maybe_unused]] constexpr int kAttestationLinkAnchor_${target} = 0; }\n")
  add_custom_command(OUTPUT "${link_force}"
    COMMAND "${CMAKE_COMMAND}" -E touch "${link_force}" VERBATIM)
  add_custom_command(OUTPUT "${link_anchor}"
    COMMAND "${CMAKE_COMMAND}" -E touch "${link_anchor}"
    DEPENDS "${link_force}" VERBATIM)
  set_source_files_properties("${link_force}" PROPERTIES
    GENERATED TRUE SYMBOLIC TRUE HEADER_FILE_ONLY TRUE)
  set_source_files_properties("${link_anchor}" PROPERTIES GENERATED TRUE SYMBOLIC TRUE)
  set_property(SOURCE "${link_anchor}" APPEND PROPERTY OBJECT_DEPENDS "${link_force}")
  target_sources("${target}" PRIVATE "${link_force}" "${link_anchor}")
  set_property(TARGET "${target}" APPEND PROPERTY LINK_DEPENDS "${link_force}")
endfunction()
add_library(attestation STATIC "${generated}")
require_fresh_attestation(attestation)
set_property(TARGET attestation APPEND PROPERTY INTERFACE_LINK_DEPENDS "${force}")
target_include_directories(attestation PUBLIC "${CMAKE_SOURCE_DIR}/include")
add_executable(probe main.cpp payload.cpp)
target_link_libraries(probe PRIVATE attestation)
require_fresh_attestation(probe)
]=])
file(WRITE "${repo}/CMakeLists.txt" "${project_text}")

foreach(command IN ITEMS init config_name config_email add commit)
  if(command STREQUAL init)
    set(arguments init)
  elseif(command STREQUAL config_name)
    set(arguments config user.name "Attestation Test")
  elseif(command STREQUAL config_email)
    set(arguments config user.email "attestation@example.invalid")
  elseif(command STREQUAL add)
    set(arguments add .)
  else()
    set(arguments commit -m initial)
  endif()
  execute_process(COMMAND "${git_executable}" ${arguments} WORKING_DIRECTORY "${repo}"
                  RESULT_VARIABLE result OUTPUT_QUIET ERROR_QUIET)
  if(NOT result EQUAL 0)
    message(FATAL_ERROR "temporary Git setup failed at ${command}")
  endif()
endforeach()
execute_process(COMMAND "${git_executable}" rev-parse HEAD WORKING_DIRECTORY "${repo}"
                OUTPUT_VARIABLE first_head OUTPUT_STRIP_TRAILING_WHITESPACE)

execute_process(COMMAND "${CMAKE_COMMAND}" -S "${repo}" -B "${build}"
                RESULT_VARIABLE configure_result OUTPUT_QUIET ERROR_QUIET)
if(NOT configure_result EQUAL 0)
  message(FATAL_ERROR "temporary attestation configure failed")
endif()

function(build_and_read output_name)
  execute_process(COMMAND "${CMAKE_COMMAND}" --build "${build}"
                  RESULT_VARIABLE build_result OUTPUT_QUIET ERROR_QUIET)
  execute_process(COMMAND "${build}/probe" RESULT_VARIABLE probe_result
                  OUTPUT_VARIABLE probe_output OUTPUT_STRIP_TRAILING_WHITESPACE)
  if(NOT build_result EQUAL 0 OR NOT probe_result EQUAL 0)
    message(FATAL_ERROR "temporary attestation build failed")
  endif()
  set(${output_name} "${probe_output}" PARENT_SCOPE)
endfunction()

build_and_read(clean_initial)
if(NOT clean_initial MATCHES "^${first_head}\\|clean\\|[0-9a-f]+$")
  message(FATAL_ERROR "clean exact-commit build was not attested")
endif()
string(REGEX REPLACE "^.*\\|" "" clean_digest "${clean_initial}")

file(APPEND "${repo}/payload.cpp" "\n")
build_and_read(dirty_trailing_newline)
if(NOT dirty_trailing_newline MATCHES "^${first_head}\\|dirty\\|[0-9a-f]+$")
  message(FATAL_ERROR "existing-source edit was not picked up by a normal rebuild")
endif()
string(REGEX REPLACE "^.*\\|" "" newline_digest "${dirty_trailing_newline}")
file(APPEND "${repo}/payload.cpp" " ")
build_and_read(dirty_trailing_space)
string(REGEX REPLACE "^.*\\|" "" space_digest "${dirty_trailing_space}")
if(newline_digest STREQUAL space_digest OR clean_digest STREQUAL newline_digest)
  message(FATAL_ERROR "trailing source bytes did not produce distinct exact tree digests: "
                      "${dirty_trailing_newline} / ${dirty_trailing_space}")
endif()

execute_process(COMMAND "${git_executable}" add payload.cpp WORKING_DIRECTORY "${repo}")
execute_process(COMMAND "${git_executable}" commit -m second WORKING_DIRECTORY "${repo}"
                RESULT_VARIABLE commit_result OUTPUT_QUIET ERROR_QUIET)
execute_process(COMMAND "${git_executable}" rev-parse HEAD WORKING_DIRECTORY "${repo}"
                OUTPUT_VARIABLE second_head OUTPUT_STRIP_TRAILING_WHITESPACE)
if(NOT commit_result EQUAL 0 OR second_head STREQUAL first_head)
  message(FATAL_ERROR "temporary second commit failed")
endif()
build_and_read(clean_second)
if(NOT clean_second MATCHES "^${second_head}\\|clean\\|[0-9a-f]+$")
  message(FATAL_ERROR "new clean HEAD was not picked up by rebuild")
endif()
execute_process(COMMAND "${git_executable}" checkout --detach "${first_head}"
                WORKING_DIRECTORY "${repo}" RESULT_VARIABLE switch_result
                OUTPUT_QUIET ERROR_QUIET)
build_and_read(clean_switched)
if(NOT switch_result EQUAL 0 OR
   NOT clean_switched MATCHES "^${first_head}\\|clean\\|[0-9a-f]+$")
  message(FATAL_ERROR "HEAD switch was not picked up by normal rebuild")
endif()
