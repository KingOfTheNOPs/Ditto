#include <stdarg.h>

int coff_silent_vprintf(const char *fmt, va_list args) {
    (void)fmt;
    (void)args;
    return 0;
}
