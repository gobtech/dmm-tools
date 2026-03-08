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
        callback = getattr(_thread_local, 'on_write', None)
        if buf is not None:
            buf.write(text)
            if callback:
                callback(text)
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
def capture_stdout(on_write=None):
    """Context manager that captures stdout for the current thread only.

    Args:
        on_write: Optional callback function(text) called on every write.
    """
    buf = io.StringIO()
    if isinstance(sys.stdout, ThreadLocalStdout):
        _thread_local.capture_buf = buf
        _thread_local.on_write = on_write
        try:
            yield buf
        finally:
            _thread_local.capture_buf = None
            _thread_local.on_write = None
    else:
        old = sys.stdout
        sys.stdout = buf
        # Fallback mode doesn't support on_write as easily without a proxy
        try:
            yield buf
        finally:
            sys.stdout = old


def install_proxy():
    """Install the thread-local stdout proxy. Call once at app startup."""
    if not isinstance(sys.stdout, ThreadLocalStdout):
        sys.stdout = ThreadLocalStdout()
