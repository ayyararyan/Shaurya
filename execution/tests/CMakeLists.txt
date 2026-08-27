find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)

add_executable(test_build_attestation test_build_attestation.cpp)
target_link_libraries(test_build_attestation PRIVATE shaurya_execution_build)
shaurya_apply_warnings(test_build_attestation)
add_test(NAME execution.build_attestation COMMAND test_build_attestation)

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
