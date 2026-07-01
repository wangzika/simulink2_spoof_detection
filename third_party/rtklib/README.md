Vendored RTKLIB Tree
====================

This directory contains the local RTKLIB source tree used by the paper
pipeline. The original ROS/catkin package files are kept for traceability, but
the project builds RTKLIB through `standalone/CMakeLists.txt` so the GNSS
post-processing step does not require ROS.

Main entry point:

- `standalone/rtklib_postpos_cli.cpp` wraps RTKLIB `postpos()` for batch RINEX
  processing.
- The top-level project target `rtklib_full_pos` builds this standalone CLI and
  generates `../full_data/gnss/rtklib_full.pos` from rover/base observations and
  the broadcast navigation file.

Before public redistribution, confirm the exact license of the upstream RTKLIB
fork represented by this local tree; the imported ROS package metadata still
contains `TODO` in `package.xml`.
