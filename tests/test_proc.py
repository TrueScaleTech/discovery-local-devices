"""Running system commands: the timeout path must not leave a broken thread behind."""

from __future__ import annotations

import sys
import threading
import time

from discovery_now._proc import run_capture

# Bytes 255 and 254 are not valid UTF-8. They are spelled as numbers so the source
# file contains no escape sequences to be mangled on the way.
INVALID_UTF8_OUTPUT = (
    "import sys; sys.stdout.buffer.write(bytes([111, 107, 32, 255, 254, 32, 100, 111, 110, 101]))"
)


def python(code: str) -> list[str]:
    """A command that behaves the same on every platform: this interpreter."""
    return [sys.executable, "-c", code]


class TestRunCapture:
    def test_returns_status_and_output(self) -> None:
        assert run_capture(python("print('hello')"), timeout=10.0) == (0, "hello" + _eol())

    def test_a_failing_command_reports_its_status(self) -> None:
        finished = run_capture(python("import sys; sys.exit(3)"), timeout=10.0)
        assert finished is not None
        assert finished[0] == 3

    def test_a_missing_program_is_none_not_an_exception(self) -> None:
        assert run_capture(["definitely-not-a-real-program-xyz"], timeout=1.0) is None

    def test_a_command_that_overruns_is_none(self) -> None:
        started = time.monotonic()
        assert run_capture(python("import time; time.sleep(30)"), timeout=0.5) is None
        # It is cut off at the limit, not waited for to the end.
        assert time.monotonic() - started < 10.0

    def test_undecodable_output_does_not_raise(self) -> None:
        finished = run_capture(python(INVALID_UTF8_OUTPUT), timeout=10.0)
        assert finished is not None
        assert "ok" in finished[1] and "done" in finished[1]


class TestTimeoutLeavesNoBrokenThread:
    """Overrunning commands must not leave an uncaught exception in a reader thread.

    Output is read on helper threads, so a failure there never reaches the caller:
    the only way to see it is to listen for uncaught thread exceptions. This is a
    guard on the cleanup path; the cap on parallel pings, tested in ``test_probes``,
    is what removed the error seen when scanning with many pings at once.
    """

    def test_overrunning_commands_raise_nothing_in_any_thread(self) -> None:
        raised: list[BaseException] = []
        previous = threading.excepthook
        threading.excepthook = lambda args: raised.append(args.exc_value or RuntimeError())
        try:
            workers = [
                threading.Thread(
                    target=run_capture,
                    args=(python("import time; time.sleep(30)"),),
                    kwargs={"timeout": 0.3},
                )
                for _ in range(8)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=30)
            # Reader threads end after the workers do; give them a moment.
            time.sleep(0.5)
        finally:
            threading.excepthook = previous
        assert raised == []


def _eol() -> str:
    """The line ending this platform's ``print`` writes."""
    return "\r\n" if sys.platform == "win32" else "\n"
