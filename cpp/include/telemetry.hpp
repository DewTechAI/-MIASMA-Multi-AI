#pragma once
#include <string>

// Collects a hardware telemetry snapshot and returns it as a JSON object.
// cpu_percent is computed over a short sampling window.
std::string collect_snapshot();
