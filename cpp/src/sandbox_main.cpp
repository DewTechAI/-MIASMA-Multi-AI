// sandbox_exec CLI: runs a command under resource limits and prints a JSON result.
// usage: sandbox_exec --mem-mb N --cpu-seconds N --wall-seconds N -- <argv...>
#include "sandbox.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

static std::string json_escape(const std::string& s) {
    std::string out;
    for (char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if ((unsigned char)c < 0x20) {
                    char b[8]; std::snprintf(b, sizeof b, "\\u%04x", c); out += b;
                } else out += c;
        }
    }
    return out;
}

int main(int argc, char** argv) {
    long mem_mb = 512, cpu_sec = 30, wall_sec = 60;
    std::vector<std::string> cmd;
    bool past_sep = false;

    for (int i = 1; i < argc; ++i) {
        if (!past_sep && !std::strcmp(argv[i], "--")) { past_sep = true; continue; }
        if (!past_sep && !std::strcmp(argv[i], "--mem-mb") && i + 1 < argc) mem_mb = std::atol(argv[++i]);
        else if (!past_sep && !std::strcmp(argv[i], "--cpu-seconds") && i + 1 < argc) cpu_sec = std::atol(argv[++i]);
        else if (!past_sep && !std::strcmp(argv[i], "--wall-seconds") && i + 1 < argc) wall_sec = std::atol(argv[++i]);
        else if (!past_sep && argv[i][0] == '-') {
            std::fprintf(stderr, "unknown flag: %s\n", argv[i]); return 2;
        } else cmd.push_back(argv[i]);
    }
    if (cmd.empty()) {
        std::fprintf(stderr, "usage: sandbox_exec [--mem-mb N] [--cpu-seconds N] [--wall-seconds N] -- <cmd...>\n");
        return 2;
    }

    SandboxResult r = sandbox_exec(cmd, mem_mb, cpu_sec, wall_sec);

    std::string out;
    out += "{\"exit_code\":" + std::to_string(r.exit_code);
    out += ",\"timed_out\":" + std::string(r.timed_out ? "true" : "false");
    out += ",\"mem_killed\":" + std::string(r.mem_killed ? "true" : "false");
    out += ",\"peak_rss_mb\":" + std::to_string(r.peak_rss_mb);
    out += ",\"stdout\":\"" + json_escape(r.stdout_text) + "\"";
    out += ",\"stderr\":\"" + json_escape(r.stderr_text) + "\"";
    out += "}";
    std::puts(out.c_str());
    return 0;
}
