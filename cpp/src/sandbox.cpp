#include "sandbox.hpp"

#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstring>
#include <fcntl.h>
#include <string>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace {

void set_limits(long mem_mb, long cpu_seconds) {
    if (mem_mb > 0) {
        rlimit rl{(rlim_t)mem_mb * 1024 * 1024, (rlim_t)mem_mb * 1024 * 1024};
        setrlimit(RLIMIT_AS, &rl);
        // Cap file sizes too so a runaway can't fill the disk.
        rlimit fl{(rlim_t)64 * 1024 * 1024, (rlim_t)64 * 1024 * 1024};
        setrlimit(RLIMIT_FSIZE, &fl);
    }
    if (cpu_seconds > 0) {
        rlimit rl{(rlim_t)cpu_seconds, (rlim_t)cpu_seconds};
        setrlimit(RLIMIT_CPU, &rl);
    }
    // Drop core dumps and don't allow privilege escalation.
    rlimit core{0, 0};
    setrlimit(RLIMIT_CORE, &core);
}

std::string read_fd(int fd) {
    std::string out;
    char buf[8192];
    ssize_t n;
    while ((n = read(fd, buf, sizeof buf)) > 0) out.append(buf, (size_t)n);
    return out;
}

} // namespace

SandboxResult sandbox_exec(const std::vector<std::string>& argv,
                           long mem_mb, long cpu_seconds, long wall_seconds) {
    SandboxResult res;
    if (argv.empty()) { res.exit_code = 2; res.stderr_text = "empty argv"; return res; }

    int out_pipe[2], err_pipe[2];
    if (pipe(out_pipe) != 0 || pipe(err_pipe) != 0) {
        res.exit_code = 2; res.stderr_text = "pipe() failed"; return res;
    }

    pid_t pid = fork();
    if (pid < 0) {
        res.exit_code = 2; res.stderr_text = "fork() failed"; return res;
    }

    if (pid == 0) {
        // Child: redirect stdout/stderr, apply limits, exec.
        dup2(out_pipe[1], STDOUT_FILENO);
        dup2(err_pipe[1], STDERR_FILENO);
        close(out_pipe[0]); close(out_pipe[1]);
        close(err_pipe[0]); close(err_pipe[1]);
        set_limits(mem_mb, cpu_seconds);
        // New process group so we can kill the whole tree on timeout.
        setpgid(0, 0);

        std::vector<char*> cargv;
        for (const auto& s : argv) cargv.push_back(const_cast<char*>(s.c_str()));
        cargv.push_back(nullptr);
        execvp(cargv[0], cargv.data());
        _exit(127);
    }

    // Parent: close write ends, read outputs, wait with timeout.
    close(out_pipe[1]); close(err_pipe[1]);
    setpgid(pid, pid);

    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(wall_seconds);
    int status = 0;
    bool done = false;

    // Poll waitpid(WNOHANG) so we can enforce wall-clock timeout.
    while (std::chrono::steady_clock::now() < deadline) {
        pid_t r = waitpid(pid, &status, WNOHANG);
        if (r == pid) { done = true; break; }
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
    }

    if (!done) {
        res.timed_out = true;
        kill(-pid, SIGKILL); // kill process group
        waitpid(pid, &status, 0);
    }

    res.stdout_text = read_fd(out_pipe[0]);
    res.stderr_text = read_fd(err_pipe[0]);
    close(out_pipe[0]); close(err_pipe[0]);

    if (WIFEXITED(status)) res.exit_code = WEXITSTATUS(status);
    else if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        res.exit_code = 128 + sig;
        if (sig == SIGKILL && mem_mb > 0) res.mem_killed = true;
        if (sig == SIGXCPU) res.exit_code = 124;
    }

    struct rusage ru;
    if (getrusage(RUSAGE_CHILDREN, &ru) == 0)
        res.peak_rss_mb = ru.ru_maxrss / 1024; // KB -> MB on Linux

    return res;
}
