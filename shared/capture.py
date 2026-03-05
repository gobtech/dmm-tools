"""Thread-safe stdout capture for use across all DMM tools."""

import contextlib
import io
import sys
import threading

_real_stdout = sys.__stdout__ or sys.stdout
_thread_local = threading.local()


class ThreadLocalStdout:
    """Proxy that routes writes to a per-thread buffer when set, else to real stdout."""

    def write(self, text):
        buf = getattr(_thread_local, 'capture_buf', None)
        if buf is not None:
            buf.write(text)
        else:
            _real_stdout.write(text)

    def flush(self):
        buf = getattr(_thread_local, 'capture_buf', None)
        if buf is not None:
            buf.flush()
        else:
            _real_stdout.flush()

    def __getattr__(self, name):
        return getattr(_real_stdout, name)


@contextlib.contextmanager
def capture_stdout():
    """Context manager that captures stdout for the current thread only.

    Works whether or not the ThreadLocalStdout proxy is installed on sys.stdout.
    When the proxy is active, writes are routed to this thread's buffer.
    When not (e.g. CLI usage), falls back to swapping sys.stdout directly.
    """
    buf = io.StringIO()
    if isinstance(sys.stdout, ThreadLocalStdout):
        _thread_local.capture_buf = buf
        try:
            yield buf
        finally:
            _thread_local.capture_buf = None
    else:
        old = sys.stdout
        sys.stdout = buf
        try:
            yield buf
        finally:
            sys.stdout = old


def install_proxy():
    """Install the thread-local stdout proxy. Call once at app startup."""
    if not isinstance(sys.stdout, ThreadLocalStdout):
        sys.stdout = ThreadLocalStdout()
