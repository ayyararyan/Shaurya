cmake_minimum_required(VERSION 3.20)
project(d51_alo_smm VERSION 0.1.1 LANGUAGES CXX)

option(ALO_ENABLE_LIVE_ROUTER "Compile code paths that can submit live Kotak orders" OFF)
option(ALO_BUILD_TESTS "Build unit tests" ON)
option(ALO_NATIVE_TUNE "Tune release binary for the build host CPU" ON)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(OpenSSL REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBCURL REQUIRED IMPORTED_TARGET libcurl)
find_package(Threads REQUIRED)
find_package(Boost 1.74 REQUIRED)

add_library(alosmm
    src/config.cpp
    src/sfeed_decoder.cpp
    src/surface.cpp
    src/online_model.cpp
    src/policy.cpp
    src/stats.cpp
    src/kotak_rest.cpp
    src/sfeed_client.cpp
    src/order_router.cpp
    src/engine.cpp
)

target_include_directories(alosmm PUBLIC include ${Boost_INCLUDE_DIRS})
target_compile_definitions(alosmm PUBLIC BOOST_ERROR_CODE_HEADER_ONLY)
if(ALO_ENABLE_LIVE_ROUTER)
    target_compile_definitions(alosmm PUBLIC ALO_ENABLE_LIVE_ROUTER=1)
else()
    target_compile_definitions(alosmm PUBLIC ALO_ENABLE_LIVE_ROUTER=0)
endif()

target_compile_options(alosmm PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)
if(CMAKE_BUILD_TYPE STREQUAL "Release" AND ALO_NATIVE_TUNE AND (CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang"))
    target_compile_options(alosmm PRIVATE -O3 -march=native -mtune=native)
endif()
include(CheckIPOSupported)
check_ipo_supported(RESULT ALO_IPO_OK OUTPUT ALO_IPO_ERROR)
if(CMAKE_BUILD_TYPE STREQUAL "Release" AND ALO_IPO_OK)
    set_property(TARGET alosmm PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE)
endif()
target_link_libraries(alosmm PUBLIC PkgConfig::LIBCURL OpenSSL::SSL OpenSSL::Crypto Threads::Threads)

add_executable(alo-smm src/main.cpp)
target_link_libraries(alo-smm PRIVATE alosmm)

if(ALO_BUILD_TESTS)
  enable_testing()
  foreach(test_name IN ITEMS test_surface test_policy test_long_only test_sfeed_decoder test_order_update)
    add_executable(${test_name} tests/${test_name}.cpp)
    target_link_libraries(${test_name} PRIVATE alosmm)
    add_test(NAME ${test_name} COMMAND ${test_name})
  endforeach()
endif()

install(TARGETS alo-smm RUNTIME DESTINATION bin)
