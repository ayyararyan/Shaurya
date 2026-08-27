foreach(required IN ITEMS SOURCE_DIR OUTPUT_FILE STAMP_FILE TEMPLATE_FILE REQUESTED_REVISION
                          PROJECT_VERSION_VALUE COMPILER_ID_VALUE BUILD_TYPE_VALUE
                          LIVE_ROUTER_VALUE GIT_EXECUTABLE_VALUE)
  if(NOT DEFINED ${required})
    message(FATAL_ERROR "source attestation input ${required} is required")
  endif()
endforeach()

execute_process(
  COMMAND "${GIT_EXECUTABLE_VALUE}" rev-parse --verify HEAD
  WORKING_DIRECTORY "${SOURCE_DIR}"
  RESULT_VARIABLE head_result OUTPUT_VARIABLE source_revision
  OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
string(LENGTH "${source_revision}" revision_length)
if(NOT head_result EQUAL 0 OR NOT revision_length EQUAL 40 OR
   NOT source_revision MATCHES "^[0-9a-f]+$")
  message(FATAL_ERROR "verifiable Git HEAD is required for source attestation")
endif()
if(NOT REQUESTED_REVISION STREQUAL "unknown" AND
   NOT REQUESTED_REVISION STREQUAL source_revision)
  message(FATAL_ERROR "SHAURYA_SOURCE_REVISION override does not match verified Git HEAD")
endif()

execute_process(
  COMMAND "${GIT_EXECUTABLE_VALUE}" status --porcelain=v1 --untracked-files=all -- .
  WORKING_DIRECTORY "${SOURCE_DIR}"
  RESULT_VARIABLE status_result OUTPUT_VARIABLE source_status ERROR_QUIET)
execute_process(
  COMMAND "${GIT_EXECUTABLE_VALUE}" ls-files --cached --others --exclude-standard -- .
  WORKING_DIRECTORY "${SOURCE_DIR}"
  RESULT_VARIABLE files_result OUTPUT_VARIABLE source_files
  OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
if(NOT status_result EQUAL 0 OR NOT files_result EQUAL 0)
  message(FATAL_ERROR "verifiable Git source state is required for source attestation")
endif()
if(source_status STREQUAL "")
  set(source_state clean)
else()
  set(source_state dirty)
endif()

set(tree_evidence "")
if(NOT source_files STREQUAL "")
  string(REPLACE "\n" ";" source_file_list "${source_files}")
  foreach(source_file IN LISTS source_file_list)
    if(source_file MATCHES ";" OR source_file MATCHES "^/" OR
       source_file MATCHES "^\\.\\./" OR source_file MATCHES "/\\.\\./" OR
       NOT EXISTS "${SOURCE_DIR}/${source_file}" OR
       IS_DIRECTORY "${SOURCE_DIR}/${source_file}" OR
       IS_SYMLINK "${SOURCE_DIR}/${source_file}")
      message(FATAL_ERROR "source attestation encountered unsafe source path: ${source_file}")
    endif()
    file(SHA256 "${SOURCE_DIR}/${source_file}" file_digest)
    string(APPEND tree_evidence "${source_file}:${file_digest}\n")
  endforeach()
endif()
string(SHA256 source_tree_digest
       "${source_revision}\n${source_state}\n${source_status}${tree_evidence}")

set(PROJECT_VERSION "${PROJECT_VERSION_VALUE}")
set(SHAURYA_SOURCE_REVISION "${source_revision}")
set(SHAURYA_SOURCE_STATE "${source_state}")
set(SHAURYA_SOURCE_TREE_DIGEST "${source_tree_digest}")
set(CMAKE_CXX_COMPILER_ID "${COMPILER_ID_VALUE}")
set(CMAKE_BUILD_TYPE "${BUILD_TYPE_VALUE}")
set(SHAURYA_LIVE_ROUTER_ATTESTATION "${LIVE_ROUTER_VALUE}")
configure_file("${TEMPLATE_FILE}" "${OUTPUT_FILE}" @ONLY)
file(TOUCH "${STAMP_FILE}")
