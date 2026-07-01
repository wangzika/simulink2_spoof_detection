#pragma once

#include "rtklib/obsdt.h"
#include "rtklib/sat_state.h"
#include "rtklib/satdt.h"

namespace rtklib {

struct GNSS_Info_ZD {
    obsdt Mea;
    satdt Sat;
    sat_state ssat;
};

}  // namespace rtklib
