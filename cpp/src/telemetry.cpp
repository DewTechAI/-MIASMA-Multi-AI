#include "telemetry.hpp"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;

namespace {

struct CpuTimes { long long user, nice, system, idle, iowait, irq, softirq, steal; };

CpuTimes read_cpu_times() {
    std::ifstream f("/proc/stat");
    std::string line;
    f.clear(); f.seekg(0);
    std::getline(f, line);
    CpuTimes t{0,0,0,0,0,0,0,0};
    if (line.rfind("cpu ", 0) == 0) {
        std::istringstream ss(line.substr(4));
        ss >> t.user >> t.nice >> t.system >> t.idle >> t.iowait >> t.irq >> t.softirq >> t.steal;
    }
    return t;
}

double cpu_percent_between(const CpuTimes& a, const CpuTimes& b) {
    auto total = [](const CpuTimes& t) {
        return (double)(t.user + t.nice + t.system + t.idle + t.iowait + t.irq + t.softirq + t.steal);
    };
    auto idle = [](const CpuTimes& t) { return (double)(t.idle + t.iowait); };
    double dt = total(b) - total(a);
    double di = idle(b) - idle(a);
    if (dt <= 0) return 0.0;
    return std::max(0.0, std::min(100.0, 100.0 * (1.0 - di / dt)));
}

long long read_meminfo_kb(const char* key) {
    std::ifstream f("/proc/meminfo");
    std::string line;
    while (std::getline(f, line)) {
        if (line.rfind(key, 0) == 0) {
            long long v = 0;
            std::sscanf(line.c_str(), "%*[^:]: %lld", &v);
            return v;
        }
    }
    return 0;
}

// Escape a string for JSON.
std::string json_escape(const std::string& s) {
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
                    char buf[8]; std::snprintf(buf, sizeof buf, "\\u%04x", c);
                    out += buf;
                } else out += c;
        }
    }
    return out;
}

// Try nvidia-smi for NVIDIA GPUs. Returns JSON array string or "[]".
std::string nvidia_gpu_json() {
    if (std::system("command -v nvidia-smi >/dev/null 2>&1") != 0) return "[]";
    FILE* p = popen(
        "nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw "
        "--format=csv,noheader,nounits 2>/dev/null", "r");
    if (!p) return "[]";
    std::string out = "[";
    char buf[512];
    bool first = true;
    while (fgets(buf, sizeof buf, p)) {
        // name, util%, mem_used, mem_total, temp, power
        std::vector<std::string> fields;
        std::string cur;
        for (char* c = buf; *c; ++c) {
            if (*c == ',') { fields.push_back(cur); cur.clear(); }
            else cur += *c;
        }
        fields.push_back(cur);
        if (fields.size() < 6) continue;
        auto trim = [](std::string s) {
            size_t a = s.find_first_not_of(" \t\r\n"), b = s.find_last_not_of(" \t\r\n");
            return a == std::string::npos ? std::string() : s.substr(a, b - a + 1);
        };
        if (!first) out += ",";
        first = false;
        char num[256];
        std::snprintf(num, sizeof num,
            "{\"vendor\":\"nvidia\",\"name\":\"%s\",\"util_percent\":%.1f,"
            "\"mem_used_mb\":%.0f,\"mem_total_mb\":%.0f,\"temp_c\":%.1f,\"power_w\":%.1f}",
            json_escape(trim(fields[0])).c_str(),
            std::strtod(trim(fields[1]).c_str(), nullptr),
            std::strtod(trim(fields[2]).c_str(), nullptr),
            std::strtod(trim(fields[3]).c_str(), nullptr),
            std::strtod(trim(fields[4]).c_str(), nullptr),
            std::strtod(trim(fields[5]).c_str(), nullptr));
        out += num;
    }
    pclose(p);
    out += "]";
    return out;
}

// AMD GPU via sysfs (amdgpu driver exposes VRAM totals).
std::string amd_gpu_json() {
    std::string out = "[";
    bool first = true;
    for (const auto& card : fs::directory_iterator("/sys/class/drm")) {
        std::string name = card.path().filename().string();
        if (name.rfind("card", 0) != 0 || !card.is_directory()) continue;
        auto dev = card.path() / "device";
        std::ifstream vendor(dev / "vendor");
        std::string vend; vendor >> vend;
        if (vend != "0x1002") continue; // AMD only
        std::ifstream mem(dev / "mem_info_vram_total");
        long long total = 0, used = 0;
        if (mem) mem >> total;
        std::ifstream mu(dev / "mem_info_vram_used");
        if (mu) mu >> used;
        if (!first) out += ",";
        first = false;
        std::ifstream model(dev / "product_name");
        std::string mname; std::getline(model, mname);
        char num[512];
        std::snprintf(num, sizeof num,
            "{\"vendor\":\"amd\",\"name\":\"%s\",\"util_percent\":0.0,"
            "\"mem_used_mb\":%.0f,\"mem_total_mb\":%.0f,\"temp_c\":-1.0,\"power_w\":-1.0}",
            json_escape(mname.empty() ? name : mname).c_str(),
            used / 1048576.0, total / 1048576.0);
        out += num;
    }
    out += "]";
    return out;
}

std::string gpu_json() {
    std::string n = nvidia_gpu_json();
    if (n != "[]") return n;
    return amd_gpu_json();
}

} // namespace

std::string collect_snapshot() {
    // CPU requires two samples.
    CpuTimes a = read_cpu_times();
    std::this_thread::sleep_for(std::chrono::milliseconds(120));
    CpuTimes b = read_cpu_times();
    double cpu = cpu_percent_between(a, b);

    long long mem_total_kb = read_meminfo_kb("MemTotal");
    long long mem_avail_kb  = read_meminfo_kb("MemAvailable");
    long long mem_used_kb   = mem_total_kb - mem_avail_kb;

    char buf[2048];
    std::snprintf(buf, sizeof buf,
        "{\"ts\":%lld,\"cpu_percent\":%.1f,"
        "\"mem_total_mb\":%.0f,\"mem_used_mb\":%.0f,\"mem_percent\":%.1f,"
        "\"gpus\":%s}",
        (long long)std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count(),
        cpu,
        mem_total_kb / 1024.0, mem_used_kb / 1024.0,
        mem_total_kb > 0 ? 100.0 * mem_used_kb / mem_total_kb : 0.0,
        gpu_json().c_str());
    return std::string(buf);
}
