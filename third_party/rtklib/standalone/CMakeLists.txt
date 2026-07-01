cmake_minimum_required(VERSION 3.16)

project(rtklib_standalone LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(RTKLIB_ROOT "${CMAKE_CURRENT_LIST_DIR}/..")

find_package(Threads REQUIRED)
find_package(BLAS)
find_package(LAPACK)

find_path(EIGEN3_INCLUDE_DIR
    NAMES Eigen/Eigen
    HINTS
        /opt/homebrew/include/eigen3
        /usr/local/include/eigen3
        /usr/include/eigen3
)
if (NOT EIGEN3_INCLUDE_DIR)
    message(FATAL_ERROR "Eigen3 was not found. Install eigen or set EIGEN3_INCLUDE_DIR.")
endif()

file(GLOB RTKLIB_SRC CONFIGURE_DEPENDS
    "${RTKLIB_ROOT}/src/*.cpp"
    "${RTKLIB_ROOT}/src/rcv/*.cpp"
)
list(FILTER RTKLIB_SRC EXCLUDE REGEX ".*/rtklib_rinex_processor_node\\.cpp$")

add_library(rtklib_core STATIC ${RTKLIB_SRC})
target_include_directories(rtklib_core PUBLIC
    "${RTKLIB_ROOT}/include"
    "${EIGEN3_INCLUDE_DIR}"
)
target_compile_definitions(rtklib_core PUBLIC
    ENAGLO
    ENAGAL
    ENAQZS
    ENACMP
    NFREQ=3
    NEXOBS=3
)
target_link_libraries(rtklib_core PUBLIC Threads::Threads)
if (BLAS_FOUND)
    target_link_libraries(rtklib_core PUBLIC ${BLAS_LIBRARIES})
endif()
if (LAPACK_FOUND)
    target_link_libraries(rtklib_core PUBLIC ${LAPACK_LIBRARIES})
endif()
if (APPLE)
    target_link_libraries(rtklib_core PUBLIC "-framework Accelerate")
else()
    target_link_libraries(rtklib_core PUBLIC m)
endif()

add_executable(rtklib_postpos_cli rtklib_postpos_cli.cpp)
target_link_libraries(rtklib_postpos_cli PRIVATE rtklib_core)
