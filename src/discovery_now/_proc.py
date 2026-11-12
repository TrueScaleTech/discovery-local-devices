"""Running a short external command and reading what it prints, tidily.

Discovery Now leans on two system commands: ``ping`` for liveness and ``arp`` for
the neighbour table. Both are started through this one helper so that they all end
the same way: a command that overruns is killed and its output is drained to the
end before its pipe is closed, so no thread is left reading a pipe that has gone.

Starting commands is also the expensive kind of concurrency, and the limit on how
many run at once lives next to the code that decides it, in
:mod:`discovery_now.probes`.
"""

from __future__ import annotations

import platform
import subprocess


def _creation_flags() -> int:
    """Keep Windows from flashing a console window for every command we start."""
    if platform.system() == "Windows":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def run_capture(command: list[str], *, timeout: float) -> tuple[int, str] | None:
    """Run a command and return ``(exit status, text printed)``.

    Returns None when the command cannot be started or does not finish within
    ``timeout`` seconds. Standard error is discarded and standard input is closed:
    nothing here reads either, and each pipe left open is one more thread on
    Windows.

    The command is always a fixed argument list built by this package, never a
    string handed to a shell, and no user-supplied text reaches it.
    """
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=_creation_flags(),
        )
    except OSError:
        return None

    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        # Drain what is left. Without this the pipe is closed while its reader
        # thread is still reading it, which is exactly the Windows error above.
        process.communicate()
        return None
    except BaseException:
        # Ctrl+C or an unexpected failure: do not leave the child running.
        process.kill()
        process.wait()
        raise

    # Console output is localized and not always UTF-8, and we only read numbers
    # and addresses out of it, so undecodable bytes are replaced rather than fatal.
    return process.returncode, output.decode("utf-8", errors="replace")
