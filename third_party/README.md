# Third-party Dependencies

The ImGui desktop UI target is optional and expects the official Dear ImGui
source tree at:

```text
third_party/imgui/
```

The simulator does not vendor ImGui automatically. If network access is
available, place the official Dear ImGui repository here, then re-run CMake.

```bash
git clone --depth 1 https://github.com/ocornut/imgui.git third_party/imgui
cmake -S . -B build
cmake --build build
```

When `third_party/imgui/imgui.cpp` and GLFW are both present, CMake builds the
`f7_imgui` executable.
