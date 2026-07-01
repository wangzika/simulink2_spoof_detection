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
find_program(LATEXMK_EXECUTABLE latexmk)
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
    set(FULL_DATA_RTKLIB_POS "${CMAKE_CURRENT_SOURCE_DIR}/../full_data/gnss/rtklib.pos")
    set(FULL_DATA_DOP "${CMAKE_CURRENT_SOURCE_DIR}/../full_data/gnss/dop.txt")
    set(FULL_DATA_ROVER_OBS "${CMAKE_CURRENT_SOURCE_DIR}/../full_data/gnss/rover.obs")
    set(FULL_DATA_BROADCAST_NAV "${CMAKE_CURRENT_SOURCE_DIR}/../full_data/gnss/BRDM00DLR_S_20240290000_01D_MN.rnx")
    set(PAPER_RINEX_SUMMARY_ARGS)
    set(PAPER_RINEX_DEPS)
    set(PAPER_RAW_RESIDUAL_CLEAN_ARGS)
    set(PAPER_RAW_RESIDUAL_ATTACK_ARGS)
    set(PAPER_RAW_RESIDUAL_CLEAN_DEPS)
    set(PAPER_RAW_RESIDUAL_ATTACK_DEPS)
    set(FAST_GLIO_LOG_DIR "$ENV{FAST_GLIO_LOG_DIR}")
    if ("${FAST_GLIO_LOG_DIR}" STREQUAL "")
        set(FAST_GLIO_LOG_DIR "/Users/wangzhibo/Desktop/FAST_GLIO/FAST_LIO/Log")
    endif()
    set(FAST_GLIO_LOOSE "${FAST_GLIO_LOG_DIR}/gnss_loose_diag.csv")
    set(FAST_GLIO_RAW "${FAST_GLIO_LOG_DIR}/gnss_raw_update_log.csv")
    set(FAST_GLIO_TIGHT "${FAST_GLIO_LOG_DIR}/gnss_tight_pose.csv")
    if (EXISTS "${FULL_DATA_RTKLIB_POS}")
        add_custom_target(adapt_full_data
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/rtklib_dataset_adapter.py
                --pos ${FULL_DATA_RTKLIB_POS}
                --dop ${FULL_DATA_DOP}
                --name full_data_rtklib
                --output-dir ${CMAKE_CURRENT_BINARY_DIR}/datasets/full_data_rtklib
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            COMMENT "Adapt ../full_data/gnss/rtklib.pos into waypoint/scenario/replay files"
            VERBATIM
        )
        add_custom_target(simulate_full_data
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/rtklib_dataset_adapter.py
                --pos ${FULL_DATA_RTKLIB_POS}
                --dop ${FULL_DATA_DOP}
                --name full_data_rtklib
                --output-dir ${CMAKE_CURRENT_BINARY_DIR}/datasets/full_data_rtklib
            COMMAND $<TARGET_FILE:f7_sim>
                --scenario ${CMAKE_CURRENT_BINARY_DIR}/datasets/full_data_rtklib/full_data_rtklib.scenario
            DEPENDS f7_sim
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            COMMENT "Run f7_sim along the adapted full_data RTKLIB route"
            VERBATIM
        )
    endif()
    if (EXISTS "${FULL_DATA_ROVER_OBS}")
        set(FULL_DATA_RINEX_EPOCH_SUMMARY
            "${CMAKE_CURRENT_BINARY_DIR}/paper_platform/rinex_rover/full_data_rover_epoch_summary.csv")
        set(FULL_DATA_RINEX_SATELLITE_FEATURES
            "${CMAKE_CURRENT_BINARY_DIR}/paper_platform/rinex_rover/full_data_rover_satellite_features.csv")
        set(PAPER_RINEX_SUMMARY_ARGS --rinex-summary ${FULL_DATA_RINEX_EPOCH_SUMMARY})
        set(PAPER_RINEX_DEPS rinex_features)
        add_custom_target(rinex_features
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/extract_rinex_features.py
                --obs ${FULL_DATA_ROVER_OBS}
                --name full_data_rover
                --output-dir ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/rinex_rover
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            COMMENT "Extract per-satellite RINEX observation features from rover.obs"
            VERBATIM
        )
        if (EXISTS "${FULL_DATA_BROADCAST_NAV}" AND EXISTS "${FULL_DATA_RTKLIB_POS}")
            set(FULL_DATA_RAW_CLEAN_EPOCH_RESIDUALS
                "${CMAKE_CURRENT_BINARY_DIR}/paper_platform/raw_gnss_clean/full_data_raw_clean_raw_epoch_residuals.csv")
            set(FULL_DATA_ATTACKED_SATELLITE_FEATURES
                "${CMAKE_CURRENT_BINARY_DIR}/paper_platform/rinex_rover_attack/full_data_rover_attack_satellite_features.csv")
            set(FULL_DATA_RAW_ATTACK_EPOCH_RESIDUALS
                "${CMAKE_CURRENT_BINARY_DIR}/paper_platform/raw_gnss_attack/full_data_raw_attack_raw_epoch_residuals.csv")
            set(PAPER_RAW_RESIDUAL_CLEAN_ARGS --raw-residual-summary ${FULL_DATA_RAW_CLEAN_EPOCH_RESIDUALS})
            set(PAPER_RAW_RESIDUAL_ATTACK_ARGS --raw-residual-summary ${FULL_DATA_RAW_ATTACK_EPOCH_RESIDUALS})
            set(PAPER_RAW_RESIDUAL_CLEAN_DEPS raw_gnss_residuals)
            set(PAPER_RAW_RESIDUAL_ATTACK_DEPS raw_gnss_residuals_attack)
            add_custom_target(raw_gnss_residuals
                COMMAND ${Python3_EXECUTABLE}
                    ${CMAKE_CURRENT_SOURCE_DIR}/tools/compute_raw_gnss_residuals.py
                    --obs ${FULL_DATA_ROVER_OBS}
                    --nav ${FULL_DATA_BROADCAST_NAV}
                    --rtklib-pos ${FULL_DATA_RTKLIB_POS}
                    --systems G
                    --name full_data_raw_clean
                    --output-dir ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/raw_gnss_clean
                WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
                COMMENT "Compute GPS broadcast-ephemeris pseudorange residuals and RAIM baseline"
                VERBATIM
            )
            add_custom_target(raw_observation_attack
                COMMAND ${Python3_EXECUTABLE}
                    ${CMAKE_CURRENT_SOURCE_DIR}/tools/inject_observation_attack.py
                    --satellite-features ${FULL_DATA_RINEX_SATELLITE_FEATURES}
                    --name full_data_rover_attack
                    --output-dir ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/rinex_rover_attack
                    --relative-origin-csv ${FAST_GLIO_LOOSE}
                    --attack-window +180:+260
                    --common-delay-m 18.0
                    --per-satellite-bias-m 180.0
                    --satellite-mode list
                    --satellites G02
                    --systems G
                DEPENDS rinex_features
                WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
                COMMENT "Inject observation-level GPS pseudorange attack into RINEX satellite features"
                VERBATIM
            )
            add_custom_target(raw_gnss_residuals_attack
                COMMAND ${Python3_EXECUTABLE}
                    ${CMAKE_CURRENT_SOURCE_DIR}/tools/compute_raw_gnss_residuals.py
                    --satellite-features ${FULL_DATA_ATTACKED_SATELLITE_FEATURES}
                    --nav ${FULL_DATA_BROADCAST_NAV}
                    --rtklib-pos ${FULL_DATA_RTKLIB_POS}
                    --systems G
                    --name full_data_raw_attack
                    --output-dir ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/raw_gnss_attack
                DEPENDS raw_observation_attack
                WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
                COMMENT "Recompute raw residuals and RAIM after observation-level attack injection"
                VERBATIM
            )
        endif()
    endif()

    if (EXISTS "${FULL_DATA_RTKLIB_POS}" AND EXISTS "${FAST_GLIO_LOOSE}" AND EXISTS "${FAST_GLIO_RAW}")
        add_custom_target(paper_dataset
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/build_detection_dataset.py
                --rtklib-pos ${FULL_DATA_RTKLIB_POS}
                --dop ${FULL_DATA_DOP}
                --loose ${FAST_GLIO_LOOSE}
                --raw ${FAST_GLIO_RAW}
                --tight ${FAST_GLIO_TIGHT}
                ${PAPER_RINEX_SUMMARY_ARGS}
                ${PAPER_RAW_RESIDUAL_CLEAN_ARGS}
                --name full_data_clean
                --output-dir ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/full_data_clean
            DEPENDS ${PAPER_RINEX_DEPS} ${PAPER_RAW_RESIDUAL_CLEAN_DEPS}
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            COMMENT "Build the clean paper detection dataset from full_data and FAST_GLIO logs"
            VERBATIM
        )
        add_custom_target(paper_dataset_attack
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/build_detection_dataset.py
                --rtklib-pos ${FULL_DATA_RTKLIB_POS}
                --dop ${FULL_DATA_DOP}
                --loose ${FAST_GLIO_LOOSE}
                --raw ${FAST_GLIO_RAW}
                --tight ${FAST_GLIO_TIGHT}
                ${PAPER_RINEX_SUMMARY_ARGS}
                ${PAPER_RAW_RESIDUAL_ATTACK_ARGS}
                --name full_data_attack
                --output-dir ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/full_data_attack
                --attack-window +180:+260
                --attack-offset 8.0,-3.0,0.5
                --pseudorange-delay 18.0
            DEPENDS ${PAPER_RINEX_DEPS} ${PAPER_RAW_RESIDUAL_ATTACK_DEPS}
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            COMMENT "Build a synthetic spoofing dataset for detector evaluation"
            VERBATIM
        )
        add_custom_target(paper_eval_attack
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/evaluate_detection.py
                ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/full_data_attack/full_data_attack_detection.csv
                --output-json ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/full_data_attack/full_data_attack_metrics.json
                --output-md ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/full_data_attack/full_data_attack_metrics.md
            DEPENDS paper_dataset_attack
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            COMMENT "Evaluate the synthetic spoofing dataset"
            VERBATIM
        )
        add_custom_target(paper_eval_clean
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/evaluate_detection.py
                ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/full_data_clean/full_data_clean_detection.csv
                --output-json ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/full_data_clean/full_data_clean_metrics.json
                --output-md ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/full_data_clean/full_data_clean_metrics.md
            DEPENDS paper_dataset
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            COMMENT "Evaluate the clean full-data false alarm behavior"
            VERBATIM
        )
        add_custom_target(paper_pipeline
            DEPENDS paper_eval_clean paper_eval_attack
        )
        add_custom_target(adaptive_experiments
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/run_experiment_matrix.py
                --base-csv ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/full_data_clean/full_data_clean_detection.csv
                --output-dir ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/adaptive_experiments
            DEPENDS paper_dataset
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            COMMENT "Run adaptive sequential GLRT experiment matrix and baseline ablations"
            VERBATIM
        )
        add_custom_target(route_split_experiments
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/route_split_experiments.py
                --route full_data=${CMAKE_CURRENT_BINARY_DIR}/paper_platform/full_data_clean/full_data_clean_detection.csv
                --train-routes full_data
                --test-routes full_data
                --output-dir ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/route_split_experiments
                --strengths-m 2,10
                --ramps-s 1,20
                --attack-types position_bias,coordinated_spoof
                --adaptive-gains 1.35,2.0
                --cusum-thresholds 0.5,0.75
                --ml-max-train-rows 6000
                --ml-trees 16
            DEPENDS paper_dataset
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            COMMENT "Run route-split tuning/test evaluation with optional ML baseline"
            VERBATIM
        )
        add_custom_target(configured_route_experiments
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/run_configured_routes.py
                --config ${CMAKE_CURRENT_SOURCE_DIR}/datasets/routes.yaml
                --output-dir ${CMAKE_CURRENT_BINARY_DIR}/paper_platform/configured_route_experiments
            DEPENDS paper_dataset
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            COMMENT "Run configured multi-route experiments from datasets/routes.yaml"
            VERBATIM
        )
        add_custom_target(paper_figures
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/generate_paper_figures.py
                --output-dir ${CMAKE_CURRENT_SOURCE_DIR}/paper/figures
                --metrics-tex ${CMAKE_CURRENT_SOURCE_DIR}/paper/generated_metrics.tex
            DEPENDS paper_pipeline adaptive_experiments
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            COMMENT "Generate LaTeX paper figures from experiment outputs"
            VERBATIM
        )
        if (LATEXMK_EXECUTABLE)
            add_custom_target(paper_pdf
                COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_SOURCE_DIR}/paper/build
                COMMAND ${CMAKE_COMMAND} -E env LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 ${LATEXMK_EXECUTABLE}
                    -g
                    -pdf
                    -interaction=nonstopmode
                    -halt-on-error
                    -outdir=${CMAKE_CURRENT_SOURCE_DIR}/paper/build
                    main.tex
                DEPENDS paper_figures
                WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/paper
                COMMENT "Build the LaTeX paper PDF"
                VERBATIM
            )
        endif()
    endif()
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
    if (Python3_EXECUTABLE)
        add_test(
            NAME paper_pipeline_smoke
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/smoke_paper_pipeline.py
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        )
        add_test(
            NAME rinex_features_smoke
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/smoke_rinex_features.py
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        )
        add_test(
            NAME raw_residuals_smoke
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/smoke_raw_residuals.py
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        )
        add_test(
            NAME adaptive_detector_smoke
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/smoke_adaptive_detector.py
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        )
        add_test(
            NAME route_split_smoke
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/smoke_route_split_experiments.py
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        )
        add_test(
            NAME configured_routes_smoke
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/smoke_configured_routes.py
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        )
    endif()
endif()
