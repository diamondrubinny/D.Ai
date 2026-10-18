# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
cmake_minimum_required(VERSION 3.18)
project(dai-panel-plugin LANGUAGES CXX)

# Headers of the lxqt-panel plugin interface (fetched from the pinned upstream
# tag by build/scripts/build-panel-plugin.sh). The interface is header-only.
set(LXQT_PANEL_SRC "" CACHE PATH "lxqt-panel source tree matching the installed panel")
if(NOT EXISTS "${LXQT_PANEL_SRC}/panel/ilxqtpanelplugin.h")
    message(FATAL_ERROR "set LXQT_PANEL_SRC to an lxqt-panel source tree")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 REQUIRED COMPONENTS Widgets Network)

add_library(daicommand MODULE daicommand.cpp daicommand.h)
target_include_directories(daicommand PRIVATE "${LXQT_PANEL_SRC}/panel")
target_link_libraries(daicommand PRIVATE Qt6::Widgets Qt6::Network)
target_compile_options(daicommand PRIVATE -Wall -Wextra -fstack-protector-strong -D_FORTIFY_SOURCE=2)
target_link_options(daicommand PRIVATE -Wl,-z,relro,-z,now)

# The Living Diamond (docs/TASKBAR.md §2.1): status marks on LXQt's Start button.
add_library(daistatus MODULE daistatus.cpp daistatus.h)
target_include_directories(daistatus PRIVATE "${LXQT_PANEL_SRC}/panel")
target_link_libraries(daistatus PRIVATE Qt6::Widgets)
target_compile_options(daistatus PRIVATE -Wall -Wextra -fstack-protector-strong -D_FORTIFY_SOURCE=2)
target_link_options(daistatus PRIVATE -Wl,-z,relro,-z,now)

option(DAI_PANEL_TESTS "Build the plugin tests" OFF)
if(DAI_PANEL_TESTS)
    enable_testing()
    find_package(Qt6 REQUIRED COMPONENTS Test)
    add_executable(test_daistatus tests/test_daistatus.cpp daistatus.cpp daistatus.h)
    target_include_directories(test_daistatus PRIVATE "${LXQT_PANEL_SRC}/panel" "${CMAKE_CURRENT_SOURCE_DIR}")
    target_link_libraries(test_daistatus PRIVATE Qt6::Widgets Qt6::Test)
    add_test(NAME daistatus COMMAND test_daistatus)
    set_tests_properties(daistatus PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endif()
