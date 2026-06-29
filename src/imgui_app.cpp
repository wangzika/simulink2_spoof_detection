#include <imgui.h>
#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl3.h>

#include <GLFW/glfw3.h>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

struct Vec2 {
    float x{};
    float y{};
};

struct Sample {
    double t{};
    Vec2 truth{};
    Vec2 estimate{};
    Vec2 gps{};
    Vec2 uwb{};
    Vec2 ref{};
    double true_z{};
    double residual{};
    double glrt{};
    double threshold{};
    bool attack{};
    bool detected{};
    bool trusted{};
    bool uwb_valid{};
    bool flow_valid{};
    bool mag_valid{};
    std::string mode;
};

struct LogData {
    std::string path;
    std::vector<Sample> samples;
    double duration{};
    double max_residual{1.0};
    double max_glrt{1.0};
    double min_x{};
    double max_x{};
    double min_y{};
    double max_y{};
};

std::vector<std::string> splitCsvLine(const std::string& line) {
    std::vector<std::string> fields;
    std::string field;
    bool in_quotes = false;
    for (char c : line) {
        if (c == '"') {
            in_quotes = !in_quotes;
            continue;
        }
        if (c == ',' && !in_quotes) {
            fields.push_back(field);
            field.clear();
        } else {
            field.push_back(c);
        }
    }
    fields.push_back(field);
    return fields;
}

double parseDouble(const std::string& value) {
    return std::strtod(value.c_str(), nullptr);
}

bool fileExists(const std::string& path) {
    std::ifstream in(path);
    return static_cast<bool>(in);
}

std::string defaultLogPath(int argc, char** argv) {
    if (argc > 1) {
        return argv[1];
    }
    const std::vector<std::string> candidates{
        "build/final_simulation.csv",
        "final_simulation.csv",
        "build/simulation.csv",
        "simulation.csv",
    };
    for (const std::string& candidate : candidates) {
        if (fileExists(candidate)) {
            return candidate;
        }
    }
    return candidates.front();
}

LogData loadLog(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("failed to open CSV: " + path);
    }

    std::string line;
    std::getline(in, line);
    const std::vector<std::string> header = splitCsvLine(line);
    std::unordered_map<std::string, std::size_t> col;
    for (std::size_t i = 0; i < header.size(); ++i) {
        col[header[i]] = i;
    }

    auto value = [&](const std::vector<std::string>& row, const std::string& name) -> double {
        const auto it = col.find(name);
        if (it == col.end() || it->second >= row.size()) {
            return 0.0;
        }
        return parseDouble(row[it->second]);
    };
    auto text = [&](const std::vector<std::string>& row, const std::string& name) -> std::string {
        const auto it = col.find(name);
        if (it == col.end() || it->second >= row.size()) {
            return {};
        }
        return row[it->second];
    };

    LogData data;
    data.path = path;
    bool first = true;
    while (std::getline(in, line)) {
        if (line.empty()) {
            continue;
        }
        const std::vector<std::string> row = splitCsvLine(line);
        Sample s;
        s.t = value(row, "time_s");
        s.truth = {static_cast<float>(value(row, "true_x")), static_cast<float>(value(row, "true_y"))};
        s.estimate = {static_cast<float>(value(row, "est_x")), static_cast<float>(value(row, "est_y"))};
        s.gps = {static_cast<float>(value(row, "gps_x")), static_cast<float>(value(row, "gps_y"))};
        s.uwb = {static_cast<float>(value(row, "uwb_x")), static_cast<float>(value(row, "uwb_y"))};
        s.ref = {static_cast<float>(value(row, "ref_x")), static_cast<float>(value(row, "ref_y"))};
        s.true_z = value(row, "true_z");
        s.residual = value(row, "pseudorange_residual_rms");
        s.glrt = value(row, "glrt_statistic");
        s.threshold = value(row, "glrt_threshold");
        s.attack = value(row, "attack_active") > 0.5;
        s.detected = value(row, "detected") > 0.5;
        s.trusted = value(row, "gps_trusted") > 0.5;
        s.uwb_valid = value(row, "uwb_valid") > 0.5;
        s.flow_valid = value(row, "flow_valid") > 0.5;
        s.mag_valid = value(row, "mag_valid") > 0.5;
        s.mode = text(row, "flight_mode");
        data.samples.push_back(s);

        data.duration = std::max(data.duration, s.t);
        data.max_residual = std::max(data.max_residual, s.residual);
        data.max_glrt = std::max(data.max_glrt, std::max(s.glrt, s.threshold));
        const std::vector<Vec2> points{s.truth, s.estimate, s.gps, s.uwb, s.ref};
        for (const Vec2& p : points) {
            if (first) {
                data.min_x = data.max_x = p.x;
                data.min_y = data.max_y = p.y;
                first = false;
            } else {
                data.min_x = std::min<double>(data.min_x, p.x);
                data.max_x = std::max<double>(data.max_x, p.x);
                data.min_y = std::min<double>(data.min_y, p.y);
                data.max_y = std::max<double>(data.max_y, p.y);
            }
        }
    }

    if (data.samples.empty()) {
        throw std::runtime_error("CSV contains no samples: " + path);
    }
    return data;
}

ImU32 color(float r, float g, float b, float a = 1.0f) {
    return IM_COL32(static_cast<int>(r * 255.0f), static_cast<int>(g * 255.0f),
                    static_cast<int>(b * 255.0f), static_cast<int>(a * 255.0f));
}

ImVec2 mapPoint(const LogData& data, const Vec2& p, const ImVec2& origin, const ImVec2& size) {
    const float pad = 18.0f;
    const double dx = std::max(1e-6, data.max_x - data.min_x);
    const double dy = std::max(1e-6, data.max_y - data.min_y);
    const double scale = std::min((size.x - 2.0f * pad) / dx, (size.y - 2.0f * pad) / dy);
    const float x = origin.x + pad + static_cast<float>((p.x - data.min_x) * scale);
    const float y = origin.y + size.y - pad - static_cast<float>((p.y - data.min_y) * scale);
    return {x, y};
}

void drawPolyline(
    ImDrawList* draw,
    const LogData& data,
    const ImVec2& origin,
    const ImVec2& size,
    ImU32 line_color,
    float thickness,
    Vec2 Sample::*field,
    std::size_t limit) {
    if (limit < 2) {
        return;
    }
    for (std::size_t i = 1; i < limit; ++i) {
        const ImVec2 a = mapPoint(data, data.samples[i - 1].*field, origin, size);
        const ImVec2 b = mapPoint(data, data.samples[i].*field, origin, size);
        draw->AddLine(a, b, line_color, thickness);
    }
}

void drawTrajectoryPanel(const LogData& data, std::size_t index) {
    ImGui::TextUnformatted("Trajectory Replay");
    const ImVec2 size = ImGui::GetContentRegionAvail();
    const ImVec2 canvas_size{std::max(360.0f, size.x), std::max(360.0f, size.y - 6.0f)};
    const ImVec2 origin = ImGui::GetCursorScreenPos();
    ImGui::InvisibleButton("trajectory_canvas", canvas_size);

    ImDrawList* draw = ImGui::GetWindowDrawList();
    draw->AddRectFilled(origin, {origin.x + canvas_size.x, origin.y + canvas_size.y}, color(0.98f, 0.99f, 1.0f));
    draw->AddRect(origin, {origin.x + canvas_size.x, origin.y + canvas_size.y}, color(0.78f, 0.82f, 0.88f));

    const std::size_t limit = std::min(index + 1, data.samples.size());
    drawPolyline(draw, data, origin, canvas_size, color(0.60f, 0.63f, 0.68f), 1.2f, &Sample::ref, data.samples.size());
    drawPolyline(draw, data, origin, canvas_size, color(0.14f, 0.39f, 0.92f), 2.0f, &Sample::truth, limit);
    drawPolyline(draw, data, origin, canvas_size, color(0.95f, 0.45f, 0.10f), 1.0f, &Sample::gps, limit);

    for (std::size_t i = 1; i < limit; ++i) {
        if (!data.samples[i - 1].attack && !data.samples[i].attack) {
            continue;
        }
        const ImVec2 a = mapPoint(data, data.samples[i - 1].truth, origin, canvas_size);
        const ImVec2 b = mapPoint(data, data.samples[i].truth, origin, canvas_size);
        draw->AddLine(a, b, color(0.86f, 0.15f, 0.15f), 3.0f);
    }

    for (std::size_t i = 0; i < limit; i += 5) {
        const Sample& s = data.samples[i];
        if (!s.uwb_valid) {
            continue;
        }
        const ImVec2 p = mapPoint(data, s.uwb, origin, canvas_size);
        draw->AddCircleFilled(p, 2.4f, color(0.06f, 0.46f, 0.43f));
    }

    const Sample& current = data.samples[index];
    const ImVec2 p = mapPoint(data, current.truth, origin, canvas_size);
    draw->AddCircleFilled(p, 7.0f, color(0.10f, 0.64f, 0.25f));
    draw->AddCircle(p, 7.0f, color(0.05f, 0.09f, 0.16f), 24, 2.0f);
}

void drawPlotPanel(const LogData& data, std::size_t index) {
    ImGui::TextUnformatted("Pseudorange Residual / GLRT");
    const ImVec2 avail = ImGui::GetContentRegionAvail();
    const ImVec2 canvas_size{std::max(360.0f, avail.x), 220.0f};
    const ImVec2 origin = ImGui::GetCursorScreenPos();
    ImGui::InvisibleButton("plot_canvas", canvas_size);
    ImDrawList* draw = ImGui::GetWindowDrawList();
    draw->AddRectFilled(origin, {origin.x + canvas_size.x, origin.y + canvas_size.y}, color(1.0f, 1.0f, 1.0f));
    draw->AddRect(origin, {origin.x + canvas_size.x, origin.y + canvas_size.y}, color(0.78f, 0.82f, 0.88f));

    const float left = 42.0f;
    const float right = 16.0f;
    const float top = 18.0f;
    const float bottom = 26.0f;
    auto px = [&](double t) {
        return origin.x + left + static_cast<float>(t / std::max(1e-6, data.duration) * (canvas_size.x - left - right));
    };
    auto pyResidual = [&](double v) {
        return origin.y + canvas_size.y - bottom -
               static_cast<float>(v / std::max(1e-6, data.max_residual) * (canvas_size.y - top - bottom));
    };
    auto pyGlrt = [&](double v) {
        return origin.y + canvas_size.y - bottom -
               static_cast<float>(v / std::max(1e-6, data.max_glrt) * (canvas_size.y - top - bottom));
    };

    draw->AddLine({origin.x + left, origin.y + top}, {origin.x + left, origin.y + canvas_size.y - bottom}, color(0.74f, 0.78f, 0.84f));
    draw->AddLine({origin.x + left, origin.y + canvas_size.y - bottom}, {origin.x + canvas_size.x - right, origin.y + canvas_size.y - bottom}, color(0.74f, 0.78f, 0.84f));

    for (std::size_t i = 1; i < data.samples.size(); ++i) {
        const Sample& a = data.samples[i - 1];
        const Sample& b = data.samples[i];
        if (a.attack || b.attack) {
            draw->AddRectFilled({px(a.t), origin.y + top}, {px(b.t), origin.y + canvas_size.y - bottom}, color(0.86f, 0.15f, 0.15f, 0.12f));
        }
        draw->AddLine({px(a.t), pyResidual(a.residual)}, {px(b.t), pyResidual(b.residual)}, color(0.14f, 0.39f, 0.92f), 1.6f);
        draw->AddLine({px(a.t), pyGlrt(a.glrt)}, {px(b.t), pyGlrt(b.glrt)}, color(0.85f, 0.47f, 0.04f), 1.3f);
        draw->AddLine({px(a.t), pyGlrt(a.threshold)}, {px(b.t), pyGlrt(b.threshold)}, color(0.86f, 0.15f, 0.15f), 1.0f);
    }

    const float cursor_x = px(data.samples[index].t);
    draw->AddLine({cursor_x, origin.y + top}, {cursor_x, origin.y + canvas_size.y - bottom}, color(0.05f, 0.09f, 0.16f), 1.6f);
}

void drawStatusPanel(const LogData& data, std::size_t index) {
    const Sample& s = data.samples[index];
    const int attack_count = static_cast<int>(std::count_if(data.samples.begin(), data.samples.end(), [](const Sample& x) { return x.attack; }));
    const int detected_count = static_cast<int>(std::count_if(data.samples.begin(), data.samples.end(), [](const Sample& x) { return x.detected; }));
    const int rejected_count = static_cast<int>(std::count_if(data.samples.begin(), data.samples.end(), [](const Sample& x) { return !x.trusted; }));
    const int uwb_count = static_cast<int>(std::count_if(data.samples.begin(), data.samples.end(), [](const Sample& x) { return x.uwb_valid; }));
    const int flow_count = static_cast<int>(std::count_if(data.samples.begin(), data.samples.end(), [](const Sample& x) { return x.flow_valid; }));
    const int mag_count = static_cast<int>(std::count_if(data.samples.begin(), data.samples.end(), [](const Sample& x) { return x.mag_valid; }));

    ImGui::Text("Log: %s", data.path.c_str());
    ImGui::Separator();
    ImGui::Text("Time: %.2f / %.2f s", s.t, data.duration);
    ImGui::Text("Mode: %s", s.mode.c_str());
    ImGui::Text("GPS: %s", s.trusted ? "trusted" : "rejected");
    ImGui::Text("Attack: %s", s.attack ? "active" : "inactive");
    ImGui::Text("Detector: %s", s.detected ? "spoof detected" : "normal");
    ImGui::Text("Altitude: %.3f m", s.true_z);
    ImGui::Text("Residual RMS: %.3f m", s.residual);
    ImGui::Text("GLRT: %.2f / %.2f", s.glrt, s.threshold);
    ImGui::Separator();
    ImGui::Text("Samples: %d", static_cast<int>(data.samples.size()));
    ImGui::Text("Attack samples: %d", attack_count);
    ImGui::Text("Detected samples: %d", detected_count);
    ImGui::Text("GPS rejected: %d", rejected_count);
    ImGui::Text("UWB updates: %d", uwb_count);
    ImGui::Text("Optical flow updates: %d", flow_count);
    ImGui::Text("Mag updates: %d", mag_count);
}

} // namespace

int main(int argc, char** argv) {
    LogData data;
    try {
        data = loadLog(defaultLogPath(argc, argv));
    } catch (const std::exception& ex) {
        std::cerr << ex.what() << "\n";
        return 1;
    }

    if (!glfwInit()) {
        std::cerr << "Failed to initialize GLFW\n";
        return 1;
    }

#if defined(__APPLE__)
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 2);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GL_TRUE);
    const char* glsl_version = "#version 150";
#else
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 0);
    const char* glsl_version = "#version 130";
#endif

    GLFWwindow* window = glfwCreateWindow(1280, 820, "F7 ImGui Flight Dashboard", nullptr, nullptr);
    if (!window) {
        std::cerr << "Failed to create GLFW window\n";
        glfwTerminate();
        return 1;
    }
    glfwMakeContextCurrent(window);
    glfwSwapInterval(1);

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    ImGui::StyleColorsLight();

    ImGui_ImplGlfw_InitForOpenGL(window, true);
    ImGui_ImplOpenGL3_Init(glsl_version);

    std::size_t index = 0;
    bool playing = true;
    float speed = 1.0f;
    double last_time = glfwGetTime();

    while (!glfwWindowShouldClose(window)) {
        glfwPollEvents();

        const double now = glfwGetTime();
        const double dt = now - last_time;
        last_time = now;
        if (playing && data.samples.size() > 1) {
            const double target_t = data.samples[index].t + dt * speed;
            while (index + 1 < data.samples.size() && data.samples[index + 1].t <= target_t) {
                ++index;
            }
            if (index + 1 >= data.samples.size()) {
                playing = false;
            }
        }

        ImGui_ImplOpenGL3_NewFrame();
        ImGui_ImplGlfw_NewFrame();
        ImGui::NewFrame();

        ImGui::SetNextWindowPos({0.0f, 0.0f}, ImGuiCond_Always);
        int display_w = 0;
        int display_h = 0;
        glfwGetFramebufferSize(window, &display_w, &display_h);
        ImGui::SetNextWindowSize({static_cast<float>(display_w), static_cast<float>(display_h)}, ImGuiCond_Always);
        ImGui::Begin("F7 GPS Spoofing ImGui Dashboard", nullptr,
                     ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoCollapse);

        if (ImGui::Button(playing ? "Pause" : "Play")) {
            playing = !playing;
        }
        ImGui::SameLine();
        if (ImGui::Button("Reset")) {
            index = 0;
            playing = false;
        }
        ImGui::SameLine();
        ImGui::SetNextItemWidth(120.0f);
        ImGui::SliderFloat("Speed", &speed, 0.25f, 8.0f, "%.2fx");
        ImGui::SameLine();
        int idx_int = static_cast<int>(index);
        ImGui::SetNextItemWidth(-1.0f);
        if (ImGui::SliderInt("Sample", &idx_int, 0, static_cast<int>(data.samples.size() - 1))) {
            index = static_cast<std::size_t>(std::clamp(idx_int, 0, static_cast<int>(data.samples.size() - 1)));
            playing = false;
        }

        ImGui::Columns(2, "main_columns", true);
        ImGui::SetColumnWidth(0, 320.0f);
        drawStatusPanel(data, index);
        ImGui::NextColumn();
        drawTrajectoryPanel(data, index);
        ImGui::Columns(1);
        drawPlotPanel(data, index);

        ImGui::End();

        ImGui::Render();
        int fb_w = 0;
        int fb_h = 0;
        glfwGetFramebufferSize(window, &fb_w, &fb_h);
        glViewport(0, 0, fb_w, fb_h);
        glClearColor(0.94f, 0.96f, 0.98f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
        glfwSwapBuffers(window);
    }

    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplGlfw_Shutdown();
    ImGui::DestroyContext();
    glfwDestroyWindow(window);
    glfwTerminate();
    return 0;
}
