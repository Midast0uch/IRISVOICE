cmake_minimum_required(VERSION 3.18)
project(iris_audio)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find Python
find_package(Python REQUIRED COMPONENTS Interpreter Development NumPy)

# Find pybind11
execute_process(
    COMMAND ${Python_EXECUTABLE} -c "import pybind11; print(pybind11.get_cmake_dir())"
    OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
list(APPEND CMAKE_PREFIX_PATH ${PYBIND11_CMAKE_DIR})
find_package(pybind11 REQUIRED)

# PortAudio — use the one bundled with sounddevice (Windows)
# The build script copies headers from the sounddevice wheel before running CMake.
if(WIN32)
    set(PORTAUDIO_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/portaudio_include" CACHE PATH "PortAudio headers")
    set(PORTAUDIO_LIB "${CMAKE_CURRENT_SOURCE_DIR}/portaudio_lib/portaudio_x64.lib" CACHE PATH "PortAudio import lib")
    if(NOT EXISTS ${PORTAUDIO_INCLUDE_DIR}/portaudio.h)
        message(FATAL_ERROR "PortAudio headers not found. Run build_native.ps1 first.")
    endif()
    include_directories(${PORTAUDIO_INCLUDE_DIR})
    link_libraries(${PORTAUDIO_LIB})
else()
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(PORTAUDIO REQUIRED portaudio-2.0)
    include_directories(${PORTAUDIO_INCLUDE_DIRS})
    link_libraries(${PORTAUDIO_LIBRARIES})
endif()

pybind11_add_module(iris_audio iris_audio.cpp)

if(MSVC)
    target_compile_options(iris_audio PRIVATE /O2 /W3)
else()
    target_compile_options(iris_audio PRIVATE -O3 -Wall)
endif()
