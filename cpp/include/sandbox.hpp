#pragma once
#include <string>
#include <vector>

// Result of a sandboxed execution.
struct SandboxResult {
    int exit_code = -1;
    bool timed_out = false;
    bool mem_killed = false;
    long peak_rss_mb = 0;
    std::string stdout_text;
    std::string stderr_text;
};

// Execute a script in an isolated child process with RLIMIT-based
// memory/time limits. `argv` is the full command (e.g. {"python3","script.py"}).
SandboxResult sandbox_exec(const std::vector<std::string>& argv,
                           long mem_limit_mb,
                           long cpu_seconds,
                           long wall_seconds);
