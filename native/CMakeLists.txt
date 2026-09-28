cmake_minimum_required(VERSION 3.29)
project(inventory_sync VERSION 0.11.12 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
include(FetchContent)
# Endstone v0.11.12, BDS 1.26.51.1. The inventory wrapper layout is also
# unchanged in v0.11.11; both runtime profiles are tested before release.
FetchContent_Declare(endstone
    GIT_REPOSITORY https://github.com/EndstoneMC/endstone.git
    GIT_TAG 1c71186cba896c5e0bc432384a8a8e72dfb2a626
    SOURCE_SUBDIR inventory-sync-no-subproject)
FetchContent_MakeAvailable(endstone)
find_package(Python3 COMPONENTS Interpreter Development.SABIModule REQUIRED)
find_package(Boost REQUIRED)
find_package(EnTT REQUIRED)
find_package(expected-lite REQUIRED)
find_package(glm REQUIRED)
find_package(Microsoft.GSL REQUIRED)
find_package(raknet REQUIRED)
find_package(pybind11 REQUIRED)

# These format expressions in the pinned SDK are not accepted by standalone
# clang builds. They do not change any layout or the inventory send routine.
set(result_header "${endstone_SOURCE_DIR}/src/bedrock/platform/result.h")
file(READ "${result_header}" result_text)
string(REPLACE "std::format(\"Error: {}\\nCall stack:{}\", error, call_stack)" "std::string(\"Error: \") + error" result_text "${result_text}")
string(REPLACE "std::format(\"{}\", error_info.error)" "error_info.error.message()" result_text "${result_text}")
if(NOT result_text MATCHES "Inventory Share standalone formatting compatibility")
    string(PREPEND result_text "// Inventory Share standalone formatting compatibility: two format expressions changed.\n")
endif()
file(WRITE "${result_header}" "${result_text}")
set(ENDSTONE_VERSION_FULL "0.11.12")
configure_file("${endstone_SOURCE_DIR}/include/endstone/version.h.in" "include/endstone/version.h" @ONLY)

add_library(inventory_sync SHARED refresh.cpp
    "${endstone_SOURCE_DIR}/src/bedrock/core/string/string_hash.cpp"
    "${endstone_SOURCE_DIR}/src/bedrock/core/sem_ver/sem_version.cpp"
    "${endstone_SOURCE_DIR}/src/bedrock/resources/base_game_version.cpp")
target_include_directories(inventory_sync PRIVATE
    "${endstone_SOURCE_DIR}/include" "${endstone_SOURCE_DIR}/src" "${CMAKE_CURRENT_BINARY_DIR}/include")
target_link_libraries(inventory_sync PRIVATE Python3::SABIModule Boost::headers EnTT::EnTT
    nonstd::expected-lite glm::glm Microsoft.GSL::GSL raknet::raknet pybind11::headers)
target_compile_definitions(inventory_sync PRIVATE ENTT_NO_MIXIN=1 ENTT_SPARSE_PAGE=2048 ENTT_PACKED_PAGE=128)
if(MSVC)
    if(NOT CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
        message(FATAL_ERROR "Use clang-cl to compile the pinned SDK bridge")
    endif()
    target_compile_options(inventory_sync PRIVATE /clang:-fno-access-control /clang:-fms-extensions)
else()
    target_compile_options(inventory_sync PRIVATE -fno-access-control -fms-extensions -stdlib=libc++)
    target_link_options(inventory_sync PRIVATE -stdlib=libc++ -static-libstdc++ -shared-libgcc)
endif()
set_target_properties(inventory_sync PROPERTIES PREFIX "" CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES BUILD_RPATH "" INSTALL_RPATH "")
install(TARGETS inventory_sync LIBRARY DESTINATION . RUNTIME DESTINATION .)
