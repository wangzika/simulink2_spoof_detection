cmake_minimum_required(VERSION 3.16)

project(f7_flight_sim
    VERSION 0.1.0
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(flight_sim
    src/controller.cpp
    src/detector.cpp
    src/dynamics.cpp
    src/flight_state_machine.cpp
    src/gnss.cpp
    src/inav_parameters.cpp
    src/navigation.cpp
    src/sensors.cpp
    src/simulator.cpp
    src/trajectory.cpp
    src/visualizer.cpp
)

target_include_directories(flight_sim PUBLIC include)

if (CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(flight_sim PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(f7_sim src/main.cpp)
target_link_libraries(f7_sim PRIVATE flight_sim)

find_package(Python3 COMPONENTS Interpreter QUIET)
if (Python3_EXECUTABLE)
    add_custom_target(rerun_view
        COMMAND $<TARGET_FILE:f7_sim>
            --output ${CMAKE_CURRENT_BINARY_DIR}/final_simulation.csv
            --html ${CMAKE_CURRENT_BINARY_DIR}/final_dashboard.html
        COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/tools/rerun_viewer.py
            ${CMAKE_CURRENT_BINARY_DIR}/final_simulation.csv
        DEPENDS f7_sim
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        COMMENT "Generate the simulation CSV and open it in Rerun"
        VERBATIM
    )
    add_custom_target(rerun_record
        COMMAND $<TARGET_FILE:f7_sim>
            --output ${CMAKE_CURRENT_BINARY_DIR}/final_simulation.csv
            --html ${CMAKE_CURRENT_BINARY_DIR}/final_dashboard.html
        COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/tools/rerun_viewer.py
            ${CMAKE_CURRENT_BINARY_DIR}/final_simulation.csv
            --save ${CMAKE_CURRENT_BINARY_DIR}/final_simulation.rrd
            --no-spawn
        DEPENDS f7_sim
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        COMMENT "Generate a Rerun .rrd recording from the simulation CSV"
        VERBATIM
    )
else()
    message(STATUS "rerun_view disabled: Python3 interpreter was not found")
endif()

set(IMGUI_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/imgui")
find_path(GLFW_INCLUDE_DIR
    NAMES GLFW/glfw3.h
    HINTS
        /opt/homebrew/opt/glfw/include
        /opt/local/include
        /usr/local/include
)
find_library(GLFW_LIBRARY
    NAMES glfw glfw3
    HINTS
        /opt/homebrew/opt/glfw/lib
        /opt/local/lib
        /usr/local/lib
)

if (EXISTS "${IMGUI_DIR}/imgui.cpp" AND GLFW_INCLUDE_DIR AND GLFW_LIBRARY)
    find_package(OpenGL REQUIRED)
    add_executable(f7_imgui MACOSX_BUNDLE
        src/imgui_app.cpp
        ${IMGUI_DIR}/imgui.cpp
        ${IMGUI_DIR}/imgui_draw.cpp
        ${IMGUI_DIR}/imgui_tables.cpp
        ${IMGUI_DIR}/imgui_widgets.cpp
        ${IMGUI_DIR}/backends/imgui_impl_glfw.cpp
        ${IMGUI_DIR}/backends/imgui_impl_opengl3.cpp
    )
    target_include_directories(f7_imgui PRIVATE
        ${IMGUI_DIR}
        ${IMGUI_DIR}/backends
        ${GLFW_INCLUDE_DIR}
    )
    target_link_libraries(f7_imgui PRIVATE ${GLFW_LIBRARY} OpenGL::GL)
    if (APPLE)
        set_target_properties(f7_imgui PROPERTIES
            MACOSX_BUNDLE_BUNDLE_NAME "F7 ImGui Dashboard"
            MACOSX_BUNDLE_GUI_IDENTIFIER "local.flight_sim.f7_imgui"
            MACOSX_BUNDLE_SHORT_VERSION_STRING "${PROJECT_VERSION}"
            MACOSX_BUNDLE_BUNDLE_VERSION "${PROJECT_VERSION}"
        )
        target_compile_definitions(f7_imgui PRIVATE GL_SILENCE_DEPRECATION)
        target_link_libraries(f7_imgui PRIVATE "-framework Cocoa" "-framework IOKit" "-framework CoreVideo")
    endif()
    if (CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
        target_compile_options(f7_imgui PRIVATE -Wall -Wextra -Wpedantic)
    endif()
else()
    message(STATUS "f7_imgui disabled: place Dear ImGui sources in third_party/imgui and install GLFW to build the ImGui UI")
endif()

include(CTest)
if (BUILD_TESTING)
    add_executable(flight_sim_tests tests/test_flight_sim.cpp)
    target_link_libraries(flight_sim_tests PRIVATE flight_sim)
    add_test(NAME flight_sim_tests COMMAND flight_sim_tests)
endif()
