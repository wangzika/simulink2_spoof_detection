#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "rtklib.h"

namespace {

bool parse_time(const std::string& text, gtime_t* time)
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

void configure_defaults(prcopt_t* popt, solopt_t* sopt)
{
    *popt = prcopt_default;
    *sopt = solopt_default;

    popt->mode = PMODE_KINEMA;
    popt->navsys = SYS_GPS | SYS_GAL | SYS_CMP;
    popt->nf = 3;
    popt->sateph = EPHOPT_BRDC;
    popt->ionoopt = IONOOPT_BRDC;
    popt->tropopt = TROPOPT_SAAS;
    popt->elmin = 10.0 * D2R;
    popt->dynamics = 1;
    popt->modear = ARMODE_CONT;
    popt->glomodear = GLO_ARMODE_OFF;
    popt->bdsmodear = 0;
    popt->refpos = POSOPT_RINEX;

    sopt->posf = SOLF_XYZ;
    sopt->times = TIMES_GPST;
    sopt->timef = 0;
    sopt->timeu = 3;
    sopt->outhead = 1;
    sopt->outopt = 1;
}

void usage(const char* argv0)
{
    std::cerr
        << "Usage: " << argv0 << " --rover OBS --base OBS --nav NAV --output POS [options]\n"
        << "\nOptions:\n"
        << "  --config CONF                  RTKLIB option file. Overrides defaults.\n"
        << "  --start \"YYYY/MM/DD HH:MM:SS\"  Optional start time.\n"
        << "  --end \"YYYY/MM/DD HH:MM:SS\"    Optional end time.\n"
        << "  --interval SEC                 Output interval passed to postpos(). Default 0.\n"
        << "  --unit SEC                     Processing unit passed to postpos(). Default 0.\n"
        << "  --nav NAV                      Can be repeated for multiple navigation files.\n";
}

int count_solution_rows(const std::string& path)
{
    std::ifstream input(path);
    int rows = 0;
    std::string line;
    while (std::getline(input, line)) {
        const auto first = line.find_first_not_of(" \t\r\n");
        if (first == std::string::npos || line[first] == '%') {
            continue;
        }
        ++rows;
    }
    return rows;
}

}  // namespace

int main(int argc, char** argv)
{
    std::string rover_obs;
    std::string base_obs;
    std::vector<std::string> nav_files;
    std::string output_pos;
    std::string config_file;
    std::string start_time;
    std::string end_time;
    double interval = 0.0;
    double unit = 0.0;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto require_value = [&](const char* name) -> std::string {
            if (i + 1 >= argc) {
                std::cerr << "Missing value for " << name << "\n";
                usage(argv[0]);
                std::exit(2);
            }
            return argv[++i];
        };

        if (arg == "--rover") {
            rover_obs = require_value("--rover");
        } else if (arg == "--base") {
            base_obs = require_value("--base");
        } else if (arg == "--nav") {
            nav_files.push_back(require_value("--nav"));
        } else if (arg == "--output") {
            output_pos = require_value("--output");
        } else if (arg == "--config") {
            config_file = require_value("--config");
        } else if (arg == "--start") {
            start_time = require_value("--start");
        } else if (arg == "--end") {
            end_time = require_value("--end");
        } else if (arg == "--interval") {
            interval = std::stod(require_value("--interval"));
        } else if (arg == "--unit") {
            unit = std::stod(require_value("--unit"));
        } else if (arg == "--help" || arg == "-h") {
            usage(argv[0]);
            return 0;
        } else {
            std::cerr << "Unknown argument: " << arg << "\n";
            usage(argv[0]);
            return 2;
        }
    }

    if (rover_obs.empty() || base_obs.empty() || nav_files.empty() || output_pos.empty()) {
        usage(argv[0]);
        return 2;
    }

    prcopt_t popt;
    solopt_t sopt;
    filopt_t fopt = {0};
    if (!config_file.empty()) {
        resetsysopts();
        if (!loadopts(config_file.c_str(), sysopts)) {
            std::cerr << "Failed to load RTKLIB config: " << config_file << "\n";
            return 1;
        }
        getsysopts(&popt, &sopt, &fopt);
    } else {
        configure_defaults(&popt, &sopt);
    }

    gtime_t ts = {0};
    gtime_t te = {0};
    if (!parse_time(start_time, &ts)) {
        std::cerr << "Invalid --start time: " << start_time << "\n";
        return 2;
    }
    if (!parse_time(end_time, &te)) {
        std::cerr << "Invalid --end time: " << end_time << "\n";
        return 2;
    }

    std::vector<std::string> inputs;
    inputs.push_back(rover_obs);
    inputs.push_back(base_obs);
    inputs.insert(inputs.end(), nav_files.begin(), nav_files.end());

    std::vector<char*> input_ptrs;
    input_ptrs.reserve(inputs.size());
    for (std::string& input : inputs) {
        input_ptrs.push_back(input.data());
    }
    std::vector<char> output(output_pos.begin(), output_pos.end());
    output.push_back('\0');

    std::cerr << "Starting RTKLIB post-processing\n"
              << "  rover:  " << rover_obs << "\n"
              << "  base:   " << base_obs << "\n"
              << "  nav:    " << nav_files.size() << " file(s)\n"
              << "  output: " << output_pos << "\n";

    const int status = postpos(ts, te, interval, unit, &popt, &sopt, &fopt,
                               input_ptrs.data(), static_cast<int>(input_ptrs.size()),
                               output.data(), "", "");
    if (status <= 0) {
        const int rows = count_solution_rows(output_pos);
        if (rows > 0) {
            std::cerr << "RTKLIB post-processing returned status=" << status
                      << " but wrote " << rows << " solution rows; treating output as valid.\n";
            return 0;
        }
        std::cerr << "RTKLIB post-processing failed with status=" << status << "\n";
        return 1;
    }
    std::cerr << "RTKLIB post-processing finished: " << output_pos << "\n";
    return 0;
}
