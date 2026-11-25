cmake_minimum_required(VERSION 3.16)
project(multi_ai_native CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_BUILD_TYPE Release)

add_executable(hwmon src/main.cpp src/telemetry.cpp)
target_include_directories(hwmon PRIVATE include)

add_executable(sandbox_exec src/sandbox_main.cpp src/sandbox.cpp)
target_include_directories(sandbox_exec PRIVATE include)
