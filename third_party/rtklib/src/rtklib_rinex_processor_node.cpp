#include <ros/ros.h>

#include <cerrno>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "rtklib.h"

namespace {

bool fileExists(const std::string& path)
{
    FILE* fp = fopen(path.c_str(), "rb");
    if (!fp) {
        return false;
    }
    fclose(fp);
    return true;
}

bool parseTime(const std::string& text, gtime_t* time)
{
    if (text.empty()) {
        *time = {0};
        return true;
    }

    std::string normalized = text;
    for (char& c : normalized) {
        if (c == '-' || c == ':' || c == 'T') {
            c = ' ';
        }
    }
    return str2time(normalized.c_str(), 0, static_cast<int>(normalized.size()), time) == 0;
}

std::string trim(const std::string& text)
{
    const std::string whitespace = " \t\r\n";
    const size_t first = text.find_first_not_of(whitespace);
    if (first == std::string::npos) {
        return "";
    }
    const size_t last = text.find_last_not_of(whitespace);
    return text.substr(first, last - first + 1);
}

std::string configValue(const std::string& line, const std::string& key)
{
    const size_t equals = line.find('=');
    if (equals == std::string::npos) {
        return "";
    }
    if (trim(line.substr(0, equals)) != key) {
        return "";
    }

    std::string value = line.substr(equals + 1);
    const size_t comment = value.find('#');
    if (comment != std::string::npos) {
        value = value.substr(0, comment);
    }
    return trim(value);
}

void loadInputPathsFromConfig(const std::string& config_file,
                              std::string* rover_obs,
                              std::string* base_obs,
                              std::string* nav_file,
                              std::string* output_pos)
{
    std::ifstream input(config_file);
    std::string line;

    while (std::getline(input, line)) {
        const std::string inp1 = configValue(line, "inpstr1-path");
        const std::string inp2 = configValue(line, "inpstr2-path");
        const std::string inp3 = configValue(line, "inpstr3-path");
        const std::string out1 = configValue(line, "outstr1-path");

        if (rover_obs->empty() && !inp1.empty()) {
            *rover_obs = inp1;
        }
        if (base_obs->empty() && !inp2.empty()) {
            *base_obs = inp2;
        }
        if (nav_file->empty() && !inp3.empty()) {
            *nav_file = inp3;
        }
        if (*output_pos == "/tmp/rtklib_rinex_processor.pos" && !out1.empty()) {
            *output_pos = out1;
        }
    }
}

void configureDefaults(prcopt_t* popt, solopt_t* sopt)
{
    *popt = prcopt_default;
    *sopt = solopt_default;

    popt->mode = PMODE_KINEMA;
    popt->navsys = SYS_GPS | SYS_GLO | SYS_GAL | SYS_CMP;
    popt->nf = 2;
    popt->sateph = EPHOPT_BRDC;
    popt->ionoopt = IONOOPT_BRDC;
    popt->tropopt = TROPOPT_SAAS;
    popt->elmin = 10.0 * D2R;
    popt->modear = ARMODE_CONT;
    popt->glomodear = GLO_ARMODE_OFF;

    sopt->posf = SOLF_LLH;
    sopt->times = TIMES_GPST;
    sopt->timef = 1;
    sopt->timeu = 3;
    sopt->outhead = 1;
    sopt->outopt = 1;
}

}  // namespace

int main(int argc, char** argv)
{
    ros::init(argc, argv, "rtklib_rinex_processor");
    ros::NodeHandle nh;
    ros::NodeHandle pnh("~");

    std::string rover_obs;
    std::string base_obs;
    std::string nav_file;
    std::vector<std::string> nav_files;
    std::string config_file;
    std::string output_pos;
    std::string start_time;
    std::string end_time;
    std::string rover_name;
    std::string base_name;
    double interval = 0.0;
    double unit = 0.0;

    pnh.param<std::string>("rover_obs", rover_obs, "");
    pnh.param<std::string>("base_obs", base_obs, "");
    pnh.param<std::string>("nav_file", nav_file, "");
    pnh.getParam("nav_files", nav_files);
    pnh.param<std::string>("config_file", config_file, "");
    pnh.param<std::string>("output_pos", output_pos, "/tmp/rtklib_rinex_processor.pos");
    pnh.param<std::string>("start_time", start_time, "");
    pnh.param<std::string>("end_time", end_time, "");
    pnh.param<std::string>("rover_name", rover_name, "");
    pnh.param<std::string>("base_name", base_name, "");
    pnh.param<double>("interval", interval, 0.0);
    pnh.param<double>("unit", unit, 0.0);

    if (!config_file.empty()) {
        if (!fileExists(config_file)) {
            ROS_ERROR("RTKLIB config file does not exist: %s", config_file.c_str());
            return 1;
        }
        loadInputPathsFromConfig(config_file, &rover_obs, &base_obs, &nav_file, &output_pos);
    }

    if (rover_obs.empty() || base_obs.empty()) {
        ROS_ERROR("Both ~rover_obs and ~base_obs are required for RTK /gnss_raw publishing. "
                  "They can also be provided by inpstr1-path and inpstr2-path in ~config_file.");
        return 1;
    }
    if (!nav_file.empty()) {
        nav_files.push_back(nav_file);
    }
    if (nav_files.empty()) {
        ROS_ERROR("At least one navigation file is required via ~nav_file or ~nav_files.");
        return 1;
    }

    std::vector<std::string> input_paths;
    input_paths.push_back(rover_obs);
    input_paths.push_back(base_obs);
    input_paths.insert(input_paths.end(), nav_files.begin(), nav_files.end());

    for (const std::string& path : input_paths) {
        if (!fileExists(path)) {
            ROS_ERROR("Input file does not exist: %s", path.c_str());
            return 1;
        }
    }

    prcopt_t popt;
    solopt_t sopt;
    filopt_t fopt = {0};
    if (!config_file.empty()) {
        resetsysopts();
        if (!loadopts(config_file.c_str(), sysopts)) {
            ROS_ERROR("Failed to load RTKLIB config file: %s", config_file.c_str());
            return 1;
        }
        getsysopts(&popt, &sopt, &fopt);
    } else {
        configureDefaults(&popt, &sopt);
    }

    gtime_t ts = {0};
    gtime_t te = {0};
    if (!parseTime(start_time, &ts)) {
        ROS_ERROR("Invalid ~start_time. Use 'YYYY/MM/DD HH:MM:SS' or leave empty.");
        return 1;
    }
    if (!parseTime(end_time, &te)) {
        ROS_ERROR("Invalid ~end_time. Use 'YYYY/MM/DD HH:MM:SS' or leave empty.");
        return 1;
    }

    std::vector<char*> infiles;
    infiles.reserve(input_paths.size());
    for (std::string& path : input_paths) {
        infiles.push_back(const_cast<char*>(path.c_str()));
    }
    std::vector<char> outfile(output_pos.begin(), output_pos.end());
    outfile.push_back('\0');

    rtkposRegisterPub(nh);

    ROS_INFO("Starting RTKLIB post-processing: rover=%s base=%s nav_files=%zu output=%s",
             rover_obs.c_str(), base_obs.c_str(), nav_files.size(), output_pos.c_str());

    const int status = postpos(ts, te, interval, unit, &popt, &sopt, &fopt,
                               infiles.data(), static_cast<int>(infiles.size()),
                               outfile.data(), rover_name.c_str(), base_name.c_str());

    if (status <= 0) {
        ROS_ERROR("RTKLIB post-processing failed with status=%d", status);
        return 1;
    }

    ROS_INFO("RTKLIB post-processing finished. Topics published: /gnss_raw, /rtklib_odom. POS file: %s",
             output_pos.c_str());
    return 0;
}
