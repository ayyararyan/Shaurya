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
file(READ "${environment_dir}/generated/shaurya/execution/build_attestation.hpp" attestation)
if(NOT attestation MATCHES "kLiveRouter = \"off\"")
  message(FATAL_ERROR "environment bypass changed live attestation")
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
