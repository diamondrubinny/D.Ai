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
