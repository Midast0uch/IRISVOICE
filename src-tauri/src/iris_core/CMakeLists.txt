cmake_minimum_required(VERSION 3.20)
project(iris_core LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# --- Fetch Abseil + RE2 via FetchContent ---
include(FetchContent)

FetchContent_Declare(
    abseil
    GIT_REPOSITORY https://github.com/abseil/abseil-cpp.git
    GIT_TAG        20240722.0
)
set(ABSL_BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(ABSL_USE_GOOGLETEST_HEAD OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(abseil)

FetchContent_Declare(
    re2
    GIT_REPOSITORY https://github.com/google/re2.git
    GIT_TAG        2024-07-01
)
set(RE2_BUILD_TESTING OFF CACHE BOOL "" FORCE)

# Patch RE2 after populate to disable install(EXPORT) —
# Abseil targets are not in RE2's export set, causing fatal configure errors.
FetchContent_GetProperties(re2)
if(NOT re2_POPULATED)
    FetchContent_Populate(re2)
    file(STRINGS "${re2_SOURCE_DIR}/CMakeLists.txt" re2_lines)
    set(re2_filtered "")
    set(re2_skip FALSE)
    foreach(line IN LISTS re2_lines)
        if(line MATCHES "^install\\(EXPORT re2Targets")
            set(re2_skip TRUE)
        endif()
        if(NOT re2_skip)
            set(re2_filtered "${re2_filtered}${line}\n")
        endif()
        if(re2_skip AND line MATCHES "NAMESPACE re2::\\)")
            set(re2_skip FALSE)
        endif()
    endforeach()
    file(WRITE "${re2_SOURCE_DIR}/CMakeLists.txt" "${re2_filtered}")
endif()

add_subdirectory(${re2_SOURCE_DIR} ${re2_BINARY_DIR} EXCLUDE_FROM_ALL)

# --- SQLCipher (prebuilt e_sqlcipher: SQLCipher 4 with FTS5) ---------------
# The bundled sqlite3.c is PLAIN SQLite: it has no codec, so the native writer
# could not open an encrypted store (measured 2026-10-31: "PRAGMA setup
# failed: file is not a database", native init rc=-2). e_sqlcipher.dll is the
# SQLCipher build from SQLitePCLRaw; its import library was generated from the
# DLL's export table (see third_party/sqlcipher/README.md).
set(SQLCIPHER_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/sqlcipher")
set(SQLCIPHER_IMPORT_LIB "${SQLCIPHER_DIR}/e_sqlcipher.lib")
set(SQLCIPHER_RUNTIME "${SQLCIPHER_DIR}/e_sqlcipher.dll")

# IRIS core sources (sqlite3.c is NOT compiled: the SQLCipher DLL supplies it)
set(IRIS_SOURCES
    iris_core.cpp
    db_manager.cpp
    caducean.cpp
    security_sanitizer.cpp
    event_ingestor.cpp
)

add_library(iris_core SHARED ${IRIS_SOURCES})

# e_sqlcipher is built with FTS5 — the app schema's context_chunks triggers
# need it (a build without FTS5 made every native INSERT there fail).
target_compile_definitions(iris_core PRIVATE SQLCIPHER_AVAILABLE)

target_include_directories(iris_core PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party/sqlite3
    ${re2_SOURCE_DIR}
)

target_link_libraries(iris_core PRIVATE
    re2::re2
    ${SQLCIPHER_IMPORT_LIB}
)

target_compile_options(iris_core PRIVATE
    $<$<CXX_COMPILER_ID:MSVC>:/W4>
    $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-Wall -Wextra -Werror=return-type>
)

# --- Benchmark executable (compiled directly with sources, not via DLL) ---
add_executable(iris_core_bench
    iris_core_bench.cpp
    ${IRIS_SOURCES}
    ${SQLITE3_SOURCES}
)
target_include_directories(iris_core_bench PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party/sqlite3
    ${re2_SOURCE_DIR}
)
target_compile_definitions(iris_core_bench PRIVATE SQLITE_ENABLE_FTS5)
target_link_libraries(iris_core_bench PRIVATE re2::re2)
if(WIN32)
    target_link_libraries(iris_core_bench PRIVATE psapi)
endif()

# Windows: copy DLL to backend/native/ for Python ctypes + PyInstaller bundling
if(WIN32)
    add_custom_command(TARGET iris_core POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy
        "$<TARGET_FILE:iris_core>"
        "${CMAKE_SOURCE_DIR}/../../../backend/native/iris_core.dll"
        COMMAND ${CMAKE_COMMAND} -E copy
        "${SQLCIPHER_RUNTIME}"
        "${CMAKE_SOURCE_DIR}/../../../backend/native/e_sqlcipher.dll"
    )
endif()

# Unix: copy SO to backend/native/ for Python ctypes + PyInstaller bundling
if(UNIX)
    add_custom_command(TARGET iris_core POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy
        "$<TARGET_FILE:iris_core>"
        "${CMAKE_SOURCE_DIR}/../../../backend/native/libiris_core.so"
    )
endif()
