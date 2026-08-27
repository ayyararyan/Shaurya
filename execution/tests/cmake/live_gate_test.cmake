set(negative_dir "${BINARY_ROOT}/live-negative")
execute_process(
  COMMAND "${CMAKE_COMMAND}" -S "${SOURCE_DIR}" -B "${negative_dir}"
    -DSHAURYA_ENABLE_LIVE_ROUTER=ON -DBUILD_TESTING=OFF
  RESULT_VARIABLE negative_result
  OUTPUT_VARIABLE negative_stdout
  ERROR_VARIABLE negative_stderr
)
if(negative_result EQUAL 0)
  message(FATAL_ERROR "live-enabled configure unexpectedly succeeded")
endif()
string(CONCAT negative_output "${negative_stdout}" "${negative_stderr}")
if(NOT negative_output MATCHES "LIVE ROUTING REFUSED")
  message(FATAL_ERROR "live refusal diagnostic was not stable")
endif()

set(kotak_negative_dir "${BINARY_ROOT}/kotak-live-negative")
execute_process(
  COMMAND "${CMAKE_COMMAND}" -S "${SOURCE_DIR}" -B "${kotak_negative_dir}"
    -DSHAURYA_ENABLE_KOTAK_LIVE=ON -DBUILD_TESTING=OFF
  RESULT_VARIABLE kotak_negative_result
  OUTPUT_VARIABLE kotak_negative_stdout
  ERROR_VARIABLE kotak_negative_stderr
)
if(kotak_negative_result EQUAL 0)
  message(FATAL_ERROR "Kotak-live configure unexpectedly succeeded")
endif()
string(CONCAT kotak_negative_output "${kotak_negative_stdout}" "${kotak_negative_stderr}")
if(NOT kotak_negative_output MATCHES "KOTAK LIVE REFUSED")
  message(FATAL_ERROR "Kotak-live refusal diagnostic was not stable")
endif()

set(environment_dir "${BINARY_ROOT}/environment-bypass")
execute_process(
  COMMAND "${CMAKE_COMMAND}" -E env
    SHAURYA_ENABLE_LIVE_ROUTER=ON LIVE_ROUTER=ON KOTAK_LIVE=ON
    "${CMAKE_COMMAND}" -S "${SOURCE_DIR}" -B "${environment_dir}" -DBUILD_TESTING=OFF
  RESULT_VARIABLE environment_result
)
if(NOT environment_result EQUAL 0)
  message(FATAL_ERROR "environment variables incorrectly enabled or broke the default build")
endif()
file(READ "${environment_dir}/generated/build_attestation_values.cpp" attestation)
if(NOT attestation MATCHES "kLiveRouter\\[\\] = \"off\"")
  message(FATAL_ERROR "environment bypass changed live attestation")
endif()
execute_process(
  COMMAND git status --porcelain=v1 --untracked-files=all -- .
  WORKING_DIRECTORY "${SOURCE_DIR}"
  RESULT_VARIABLE source_status_result
  OUTPUT_VARIABLE source_status
  OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(NOT source_status_result EQUAL 0)
  message(FATAL_ERROR "test could not derive the actual source state")
endif()
if(source_status STREQUAL "")
  set(expected_source_state clean)
else()
  set(expected_source_state dirty)
endif()
if(NOT attestation MATCHES "kSourceState\\[\\] = \"${expected_source_state}\"" OR
   NOT attestation MATCHES "kSourceTreeDigest\\[\\] = \"[0-9a-f]+\"")
  message(FATAL_ERROR "configured attestation did not match the actual Git source state")
endif()

set(injection_dir "${BINARY_ROOT}/attestation-injection")
execute_process(
  COMMAND "${CMAKE_COMMAND}" -S "${SOURCE_DIR}" -B "${injection_dir}"
    "-DSHAURYA_SOURCE_REVISION=deadbeef live_router=on"
  RESULT_VARIABLE injection_result
)
if(injection_result EQUAL 0)
  message(FATAL_ERROR "attestation delimiter injection unexpectedly configured")
endif()

set(spoof_dir "${BINARY_ROOT}/attestation-spoof")
execute_process(
  COMMAND "${CMAKE_COMMAND}" -S "${SOURCE_DIR}" -B "${spoof_dir}"
    "-DSHAURYA_SOURCE_REVISION=0000000000000000000000000000000000000000"
    -DBUILD_TESTING=OFF
  RESULT_VARIABLE spoof_result
  OUTPUT_VARIABLE spoof_stdout
  ERROR_VARIABLE spoof_stderr
)
if(spoof_result EQUAL 0)
  message(FATAL_ERROR "valid-looking source revision spoof unexpectedly configured")
endif()
string(CONCAT spoof_output "${spoof_stdout}" "${spoof_stderr}")
if(NOT spoof_output MATCHES "does not match verified Git HEAD")
  message(FATAL_ERROR "source revision spoof refusal diagnostic was not stable")
endif()

set(no_repository_source "${BINARY_ROOT}/no-repository-source")
set(no_repository_build "${BINARY_ROOT}/no-repository-build")
file(COPY "${SOURCE_DIR}/" DESTINATION "${no_repository_source}"
     PATTERN ".git" EXCLUDE)
execute_process(
  COMMAND "${CMAKE_COMMAND}" -S "${no_repository_source}" -B "${no_repository_build}"
    -DBUILD_TESTING=OFF
  RESULT_VARIABLE no_repository_result
  OUTPUT_VARIABLE no_repository_stdout
  ERROR_VARIABLE no_repository_stderr
)
if(no_repository_result EQUAL 0)
  message(FATAL_ERROR "source tree without verifiable repository metadata unexpectedly configured")
endif()
string(CONCAT no_repository_output "${no_repository_stdout}" "${no_repository_stderr}")
if(NOT no_repository_output MATCHES "verifiable Git HEAD is required")
  message(FATAL_ERROR "missing repository attestation diagnostic was not stable")
endif()
