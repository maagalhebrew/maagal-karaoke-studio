#include <mach-o/dyld.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    char path[PATH_MAX], executable[PATH_MAX], python[PATH_MAX], script[PATH_MAX];
    uint32_t capacity = sizeof(path);
    if (_NSGetExecutablePath(path, &capacity) != 0 || !realpath(path, executable)) return 1;
    char *last = strrchr(executable, '/');
    if (!last) return 1;
    *last = '\0';
    if (snprintf(python, sizeof(python), "%s/../Resources/Studio/python/bin/python3.11", executable) >= sizeof(python)) return 1;
    if (snprintf(script, sizeof(script), "%s/../Resources/Studio/launch.py", executable) >= sizeof(script)) return 1;
    char *const args[] = {python, "-I", "-B", script, NULL};
    execv(python, args);
    return 1;
}
