#pragma once

#include "rtklib/obsdt.h"
#include "rtklib/sat_state.h"
#include "rtklib/satdt.h"

namespace rtklib {

struct GNSS_Info_SD {
    obsdt Mea_Rover;
    obsdt Mea_Base;
    satdt Sat_Rover;
    satdt Sat_Base;
    sat_state ssat;
};

}  // namespace rtklib
