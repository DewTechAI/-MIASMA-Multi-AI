#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <thread>

#include "telemetry.hpp"

static void usage(const char* prog) {
    std::fprintf(stderr,
        "usage: %s [--once | --interval MS] [--max-mem-mb N]\n"
        "  --once        print a single JSON snapshot and exit\n"
        "  --interval MS stream snapshots every MS milliseconds\n"
        "  --max-mem-mb N  kill self if RSS exceeds N MB (0 = unlimited)\n",
        prog);
}

int main(int argc, char** argv) {
    bool once = false;
    int interval_ms = 1000;
    long max_mem_mb = 0;

    for (int i = 1; i < argc; ++i) {
        if (!std::strcmp(argv[i], "--once")) once = true;
        else if (!std::strcmp(argv[i], "--interval") && i + 1 < argc) interval_ms = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "--max-mem-mb") && i + 1 < argc) max_mem_mb = std::atol(argv[++i]);
        else { usage(argv[0]); return 2; }
    }

    if (once) {
        std::puts(collect_snapshot().c_str());
        return 0;
    }

    // Streaming mode. Periodically check own RSS.
    for (;;) {
        std::puts(collect_snapshot().c_str());
        std::fflush(stdout);
        if (max_mem_mb > 0) {
            std::ifstream f("/proc/self/status");
            std::string line;
            while (std::getline(f, line)) {
                if (line.rfind("VmRSS:", 0) == 0) {
                    long rss_kb = std::atol(line.c_str() + 6);
                    if (rss_kb / 1024 > max_mem_mb) return 3;
                }
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
    }
}
