find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)

set(
  SHAURYA_ROUTING_TEST_PYTHON
  "${Python3_EXECUTABLE}"
  CACHE FILEPATH
  "Python interpreter containing the Shaurya Data runtime dependencies for routing exporter tests"
)
if(NOT IS_ABSOLUTE "${SHAURYA_ROUTING_TEST_PYTHON}" OR
   NOT EXISTS "${SHAURYA_ROUTING_TEST_PYTHON}" OR
   IS_DIRECTORY "${SHAURYA_ROUTING_TEST_PYTHON}")
  message(FATAL_ERROR
    "SHAURYA_ROUTING_TEST_PYTHON must name an existing absolute Python interpreter path")
endif()

add_executable(test_build_attestation test_build_attestation.cpp)
target_link_libraries(test_build_attestation PRIVATE shaurya_execution_build)
shaurya_apply_warnings(test_build_attestation)
add_test(NAME execution.build_attestation COMMAND test_build_attestation)

foreach(contract_test IN ITEMS canonical_json contracts)
  add_executable("test_${contract_test}" "contracts/${contract_test}_test.cpp")
  target_link_libraries("test_${contract_test}" PRIVATE shaurya_execution_contracts)
  shaurya_apply_warnings("test_${contract_test}")
  add_test(NAME "execution.${contract_test}" COMMAND "test_${contract_test}")
endforeach()
target_compile_definitions(test_contracts PRIVATE
  SHAURYA_EXECUTION_SOURCE_ROOT="${PROJECT_SOURCE_DIR}"
)

add_executable(test_instrument_resolver routing/instrument_resolver_test.cpp)
target_link_libraries(test_instrument_resolver PRIVATE shaurya_execution_contracts)
shaurya_apply_warnings(test_instrument_resolver)
add_test(NAME execution.instrument_resolver COMMAND test_instrument_resolver)

get_filename_component(SHAURYA_REPOSITORY_ROOT "${PROJECT_SOURCE_DIR}" DIRECTORY)
add_test(
  NAME execution.routing_exporter
  COMMAND "${CMAKE_COMMAND}" -E env
    "PYTHONDONTWRITEBYTECODE=1"
    "PYTHONPATH=${SHAURYA_REPOSITORY_ROOT}/data/src"
    "${SHAURYA_ROUTING_TEST_PYTHON}"
    "${CMAKE_CURRENT_SOURCE_DIR}/routing/test_routing_exporter.py" -v
)
set_tests_properties(execution.routing_exporter PROPERTIES LABELS "routing;python")

add_test(
  NAME execution.live_gate
  COMMAND "${CMAKE_COMMAND}"
    -DSOURCE_DIR=${PROJECT_SOURCE_DIR}
    -DBINARY_ROOT=${CMAKE_CURRENT_BINARY_DIR}
    -P ${CMAKE_CURRENT_SOURCE_DIR}/cmake/live_gate_test.cmake
)
add_test(
  NAME execution.project_layout
  COMMAND "${CMAKE_COMMAND}"
    -DSOURCE_DIR=${PROJECT_SOURCE_DIR}
    -DBINARY_ROOT=${CMAKE_CURRENT_BINARY_DIR}
    -P ${CMAKE_CURRENT_SOURCE_DIR}/cmake/project_layout_test.cmake
)

foreach(policy_test IN ITEMS
    test_dependency_boundaries.py
    test_spec_traceability.py
    test_repository_hygiene.py
    test_documented_boundaries.py)
  get_filename_component(policy_name "${policy_test}" NAME_WE)
  add_test(
    NAME "execution.policy.${policy_name}"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/policy/${policy_test}"
      --repo-root "${PROJECT_SOURCE_DIR}/.."
      --start-commit bcb6dea02329f824c82488f29450af0dd0e826ca
  )
  add_test(
    NAME "execution.policy.optimized.${policy_name}"
    COMMAND "${Python3_EXECUTABLE}" -O "${CMAKE_CURRENT_SOURCE_DIR}/policy/${policy_test}"
      --repo-root "${PROJECT_SOURCE_DIR}/.."
      --start-commit bcb6dea02329f824c82488f29450af0dd0e826ca
  )
endforeach()
