"""The interactive menu: what it reads from the CLI, what it builds, how it navigates."""

from __future__ import annotations

import io
import re
from collections.abc import Iterable, Sequence
from typing import Any

import pytest
import typer
from rich.console import Console, RenderableType
from typer.testing import CliRunner

from discovery_now import menu
from discovery_now.cli import app

GROUP = typer.main.get_command(app)
ROOT, GLOBALS = menu.build_tree(GROUP)
runner = CliRunner()

CTRL_C = "<ctrl-c>"


# ---------------------------------------------------------------------------
# Helpers: a scripted keyboard and screen
# ---------------------------------------------------------------------------


class FakeTerminal:
    """Stands in for the real terminal: keys and answers come from a script."""

    def __init__(self, keys: Iterable[str], answers: Iterable[str] = ()) -> None:
        self._keys = iter(keys)
        self._answers = iter(answers)
        self.history: list[str] = []
        self.frames: list[str] = []
        self.screen = ""
        self.asked: list[tuple[str, str]] = []

    @property
    def ascii_only(self) -> bool:
        return False

    @property
    def height(self) -> int:
        return 60

    def clear(self) -> None:
        if self.screen:
            self.frames.append(self.screen)
        self.screen = ""

    def show(self, renderable: RenderableType) -> None:
        buffer = io.StringIO()
        Console(file=buffer, width=110, color_system=None).print(renderable)
        self.screen += buffer.getvalue()
        self.history.append(buffer.getvalue())

    def key(self) -> str:
        try:
            key = next(self._keys)
        except StopIteration:
            # A loop that never ends would hang the test run; fail loudly instead.
            raise AssertionError("the menu asked for more keys than the test gave it") from None
        if key == CTRL_C:
            raise KeyboardInterrupt
        return key

    def ask(self, label: str, default: str = "") -> str:
        self.asked.append((label, default))
        try:
            return next(self._answers)
        except StopIteration:
            raise AssertionError("the menu asked a question the test did not answer") from None

    @property
    def last_screen(self) -> str:
        """The screen that was showing just before the menu said goodbye."""
        return self.frames[-1] if self.frames else self.screen

    @property
    def everything(self) -> str:
        return "\n".join(self.history)


def drive(
    keys: Sequence[str],
    answers: Sequence[str] = (),
    *,
    code: int = 0,
) -> tuple[FakeTerminal, list[list[str]]]:
    """Run the menu with a script and report what it tried to execute."""
    terminal = FakeTerminal(keys, answers)
    calls: list[list[str]] = []

    def fake_runner(arguments: list[str]) -> int:
        calls.append(arguments)
        return code

    menu.Menu(ROOT, GLOBALS, terminal=terminal, runner=fake_runner).run()
    return terminal, calls


def child(parent: menu.Node, name: str) -> menu.Node:
    return next(node for node in parent.children if node.name == name)


def position(parent: menu.Node, name: str) -> int:
    return [node.name for node in parent.children].index(name)


def param_position(node: menu.Node, name: str) -> int:
    return [param.name for param in node.params].index(name)


def move(start: int, end: int) -> list[str]:
    """The key presses that take a cursor from one row to another."""
    return ["down"] * (end - start) if end >= start else ["up"] * (start - end)


def open_command(*names: str) -> tuple[list[str], menu.Node]:
    """Keys that open a command from the first screen, and the command's node."""
    keys: list[str] = []
    node = ROOT
    for name in names:
        keys += [*move(0, position(node, name)), "enter"]
        node = child(node, name)
    return keys, node


def run_row(node: menu.Node, *, after: int) -> list[str]:
    """Keys from a parameter row down to Run, which is the first row after them."""
    return [*move(after, len(node.params)), "enter"]


# ---------------------------------------------------------------------------
# Reading the command tree
# ---------------------------------------------------------------------------


class TestCommandTree:
    def test_every_command_of_the_cli_is_in_the_menu(self) -> None:
        def expected(command: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[str, ...]]:
            for name, sub in command.commands.items():
                if not path and name == "menu":
                    continue
                yield (*path, name)
                if hasattr(sub, "commands"):
                    yield from expected(sub, (*path, name))

        def found(node: menu.Node) -> Iterable[tuple[str, ...]]:
            for sub in node.children:
                yield sub.path
                yield from found(sub)

        assert set(found(ROOT)) == set(expected(GROUP))

    def test_every_option_of_every_command_is_offered(self) -> None:
        # The menu is built from the parser, so this is what keeps it honest: a new
        # option added to the CLI has to show up here, or this test says so.
        def walk(command: Any, node: menu.Node) -> None:
            wanted = {
                p.name
                for p in command.params
                if not getattr(p, "hidden", False) and not getattr(p, "is_eager", False)
            }
            if node.path:
                assert {p.name for p in node.params} == wanted, node.path
            for name, sub in command.commands.items() if hasattr(command, "commands") else []:
                if not node.path and name == "menu":
                    continue
                walk(sub, child(node, name))

        walk(GROUP, ROOT)

    def test_the_menu_does_not_list_itself(self) -> None:
        assert "menu" not in [node.name for node in ROOT.children]

    def test_the_global_option_is_kept_apart(self) -> None:
        assert [param.name for param in GLOBALS] == ["config"]
        assert ROOT.params == []

    def test_groups_hold_their_commands(self) -> None:
        devices = child(ROOT, "devices")
        assert devices.is_group
        assert {"list", "show", "rename", "note", "approve", "forget"} <= {
            node.name for node in devices.children
        }

    def test_options_are_understood_by_what_they_accept(self) -> None:
        # Pinned on purpose: these come from the parser's own type information, so a
        # change in how it reports them makes this fail instead of quietly turning
        # every option into plain text.
        export = child(ROOT, "export")
        scan = child(ROOT, "scan")
        by_name = {p.name: p for p in export.params}
        scan_by_name = {p.name: p for p in scan.params}

        assert by_name["fmt"].kind is menu.Kind.CHOICE
        assert by_name["fmt"].choices == ("csv", "json")
        assert by_name["output"].kind is menu.Kind.PATH
        assert by_name["force"].kind is menu.Kind.FLAG
        assert by_name["online"].kind is menu.Kind.TOGGLE
        assert scan_by_name["timeout"].kind is menu.Kind.FLOAT
        assert scan_by_name["workers"].kind is menu.Kind.INT
        assert scan_by_name["subnet"].multiple
        assert scan_by_name["subnet"].kind is menu.Kind.TEXT

    def test_positional_arguments_are_marked_and_required(self) -> None:
        rename = child(child(ROOT, "devices"), "rename")
        assert [p.name for p in rename.params] == ["selector", "label"]
        assert all(p.positional and p.required for p in rename.params)

    def test_toggles_know_both_of_their_flags(self) -> None:
        online = next(p for p in child(ROOT, "export").params if p.name == "online")
        assert (online.on, online.off) == ("--online", "--offline")
        assert "--online" in online.label and "--offline" in online.label


# ---------------------------------------------------------------------------
# Building the command line
# ---------------------------------------------------------------------------


def flag(name: str, kind: menu.Kind, **extra: Any) -> menu.Param:
    return menu.Param(
        name=name,
        label=f"--{name}",
        kind=kind,
        on=extra.pop("on", f"--{name}"),
        flag=extra.pop("flag", f"--{name}"),
        **extra,
    )


class TestBuildArguments:
    def node(self, *params: menu.Param) -> menu.Node:
        return menu.Node("x", "", ("x",), list(params))

    def test_a_command_with_nothing_set_is_just_its_name(self) -> None:
        assert menu.build_arguments(self.node(flag("a", menu.Kind.FLAG)), {}) == ["x"]

    def test_a_flag_that_is_on(self) -> None:
        node = self.node(flag("force", menu.Kind.FLAG))
        assert menu.build_arguments(node, {"force": True}) == ["x", "--force"]

    def test_a_flag_that_is_off_is_left_out(self) -> None:
        node = self.node(flag("force", menu.Kind.FLAG))
        assert menu.build_arguments(node, {"force": False}) == ["x"]

    def test_a_toggle_in_each_of_its_states(self) -> None:
        node = self.node(flag("online", menu.Kind.TOGGLE, off="--offline"))
        assert menu.build_arguments(node, {"online": True}) == ["x", "--online"]
        assert menu.build_arguments(node, {"online": False}) == ["x", "--offline"]
        assert menu.build_arguments(node, {"online": None}) == ["x"]

    def test_a_value(self) -> None:
        node = self.node(flag("output", menu.Kind.PATH))
        assert menu.build_arguments(node, {"output": "out.csv"}) == ["x", "--output", "out.csv"]

    def test_a_repeated_option_is_given_once_per_value(self) -> None:
        node = self.node(flag("subnet", menu.Kind.TEXT, multiple=True))
        built = menu.build_arguments(node, {"subnet": ["10.0.0.0/24", "10.0.1.0/24"]})
        assert built == ["x", "--subnet", "10.0.0.0/24", "--subnet", "10.0.1.0/24"]

    def test_a_value_starting_with_a_dash_cannot_be_mistaken_for_an_option(self) -> None:
        node = self.node(flag("label", menu.Kind.TEXT))
        assert menu.build_arguments(node, {"label": "-odd"}) == ["x", "--label=-odd"]

    def test_positional_arguments_come_last(self) -> None:
        node = self.node(
            menu.Param("target", "TARGET", menu.Kind.TEXT, positional=True),
            flag("force", menu.Kind.FLAG),
        )
        built = menu.build_arguments(node, {"target": "nas", "force": True})
        assert built == ["x", "--force", "nas"]

    def test_a_positional_starting_with_a_dash_is_protected(self) -> None:
        node = self.node(menu.Param("target", "TARGET", menu.Kind.TEXT, positional=True))
        assert menu.build_arguments(node, {"target": "-x"}) == ["x", "--", "-x"]

    def test_program_wide_options_come_before_the_command(self) -> None:
        config = flag("config", menu.Kind.PATH)
        built = menu.build_arguments(self.node(), {}, [config], {"config": "settings.toml"})
        assert built == ["--config", "settings.toml", "x"]

    def test_a_command_inside_a_group_keeps_its_whole_path(self) -> None:
        rename = child(child(ROOT, "devices"), "rename")
        built = menu.build_arguments(rename, {"selector": "192.168.1.5", "label": "NAS"})
        assert built == ["devices", "rename", "192.168.1.5", "NAS"]

    def test_empty_text_counts_as_not_set(self) -> None:
        node = self.node(flag("output", menu.Kind.PATH))
        assert menu.build_arguments(node, {"output": ""}) == ["x"]


class TestRequired:
    def test_lists_what_is_missing(self) -> None:
        rename = child(child(ROOT, "devices"), "rename")
        assert [p.name for p in menu.missing_required(rename, {})] == ["selector", "label"]

    def test_nothing_is_missing_once_filled(self) -> None:
        rename = child(child(ROOT, "devices"), "rename")
        assert menu.missing_required(rename, {"selector": "a", "label": "b"}) == []


class TestCheckValue:
    def test_accepts_a_whole_number(self) -> None:
        param = menu.Param("n", "--n", menu.Kind.INT)
        assert menu.check_value(param, "12") is None

    def test_rejects_text_for_a_number(self) -> None:
        param = menu.Param("n", "--n", menu.Kind.INT)
        assert menu.check_value(param, "twelve") == "that is not a number"

    def test_a_decimal_is_not_a_whole_number(self) -> None:
        param = menu.Param("n", "--n", menu.Kind.INT)
        assert menu.check_value(param, "1.5") is not None

    def test_accepts_a_decimal_where_one_is_wanted(self) -> None:
        param = menu.Param("t", "--t", menu.Kind.FLOAT)
        assert menu.check_value(param, "0.5") is None

    def test_a_choice_must_be_on_the_list(self) -> None:
        param = menu.Param("f", "--f", menu.Kind.CHOICE, choices=("csv", "json"))
        assert menu.check_value(param, "json") is None
        assert "csv, json" in (menu.check_value(param, "xml") or "")

    def test_free_text_is_always_fine(self) -> None:
        assert menu.check_value(menu.Param("t", "--t", menu.Kind.TEXT), "anything") is None


def test_the_command_line_is_shown_as_it_would_be_typed() -> None:
    line = menu.command_line(["export", "--output", "my file.csv"])
    assert line.startswith("discoverynow export --output")
    assert "'my file.csv'" in line or '"my file.csv"' in line


class TestKeys:
    @pytest.mark.parametrize(
        ("raw", "name"),
        [
            ("\x1b[A", "up"),
            ("\xe0H", "up"),
            ("\x1b[B", "down"),
            ("\xe0P", "down"),
            ("\x1b[D", "left"),
            ("\x1b[C", "right"),
            ("\r", "enter"),
            ("\n", "enter"),
            ("\x1b", "esc"),
            ("\x7f", "backspace"),
            ("\x08", "backspace"),
            ("\x1b[3~", "delete"),
            ("\xe0S", "delete"),
        ],
    )
    def test_the_same_key_has_the_same_name_everywhere(self, raw: str, name: str) -> None:
        assert menu.normalize_key(raw) == name

    def test_an_ordinary_key_is_itself(self) -> None:
        assert menu.normalize_key("q") == "q"

    def test_an_unknown_sequence_is_ignored_not_misread(self) -> None:
        assert menu.normalize_key("\x1b[5~") == "other"


# ---------------------------------------------------------------------------
# Moving around
# ---------------------------------------------------------------------------


class TestNavigation:
    def test_q_leaves_the_menu(self) -> None:
        terminal, calls = drive(["q"])
        assert calls == []
        assert "Bye." in terminal.everything

    def test_escape_on_the_first_screen_also_leaves(self) -> None:
        _terminal, calls = drive(["esc"])
        assert calls == []

    def test_the_first_screen_lists_every_command(self) -> None:
        terminal, _ = drive(["q"])
        for node in ROOT.children:
            assert node.name in terminal.everything
        assert "Global options" in terminal.everything
        assert "Quit" in terminal.everything

    def test_the_cursor_wraps_around(self) -> None:
        # One step up from the first row lands on the last, which is Quit.
        _terminal, calls = drive(["up", "enter"])
        assert calls == []

    def test_a_group_opens_a_second_list_and_escape_comes_back(self) -> None:
        keys, _ = open_command("devices")
        terminal, _calls = drive([*keys, "esc", "q"])
        assert "rename" in terminal.everything
        assert "Inspect and annotate" in terminal.everything

    def test_vim_keys_work_too(self) -> None:
        target = position(ROOT, "interfaces")
        keys = ["j"] * target + ["enter", "enter", "x", "q"]
        _terminal, calls = drive(keys)
        assert calls == [["interfaces"]]

    def test_ctrl_c_ends_the_menu_quietly(self) -> None:
        terminal, calls = drive([CTRL_C])
        assert calls == []
        assert "Bye." in terminal.everything

    def test_it_never_waits_forever_for_a_script_that_ran_out(self) -> None:
        with pytest.raises(AssertionError, match="more keys"):
            drive([])


# ---------------------------------------------------------------------------
# Filling in a command and running it
# ---------------------------------------------------------------------------


class TestRunning:
    def test_a_command_with_no_options_runs_as_is(self) -> None:
        keys, interfaces = open_command("interfaces")
        _terminal, calls = drive([*keys, "enter", "x", "q"])
        assert interfaces.params == []
        assert calls == [["interfaces"]]

    def test_options_of_every_kind_end_up_on_the_command_line(self) -> None:
        keys, scan = open_command("scan")
        subnet = param_position(scan, "subnet")
        workers = param_position(scan, "workers")
        as_json = param_position(scan, "as_json")

        keys += [*move(0, subnet), "enter"]
        keys += [*move(subnet, workers), "enter"]
        keys += [*move(workers, as_json), "enter"]
        keys += [*run_row(scan, after=as_json), "x", "q"]

        terminal, calls = drive(keys, ["10.0.0.0/24", "", "8"])
        assert calls == [["scan", "--subnet", "10.0.0.0/24", "--workers", "8", "--json"]]
        assert "$ discoverynow scan" in terminal.everything

    def test_several_values_can_be_given_to_a_repeatable_option(self) -> None:
        keys, scan = open_command("scan")
        subnet = param_position(scan, "subnet")
        keys += [*move(0, subnet), "enter", *run_row(scan, after=subnet), "x", "q"]
        _terminal, calls = drive(keys, ["10.0.0.0/24", "10.0.1.0/24", ""])
        assert calls == [["scan", "--subnet", "10.0.0.0/24", "--subnet", "10.0.1.0/24"]]

    def test_a_bad_number_is_refused_and_asked_again(self) -> None:
        keys, scan = open_command("scan")
        workers = param_position(scan, "workers")
        keys += [*move(0, workers), "enter", *run_row(scan, after=workers), "x", "q"]
        terminal, calls = drive(keys, ["lots", "16"])
        assert calls == [["scan", "--workers", "16"]]
        assert "that is not a number" in terminal.everything

    def test_a_choice_is_picked_from_a_list(self) -> None:
        keys, export = open_command("export")
        fmt = param_position(export, "fmt")
        # The list opens on "(not set)", the last row; one step up is "json".
        keys += [*move(0, fmt), "enter", "up", "enter"]
        keys += [*run_row(export, after=fmt), "x", "q"]
        _terminal, calls = drive(keys)
        assert calls == [["export", "--format", "json"]]

    def test_a_toggle_cycles_through_unset_on_and_off(self) -> None:
        keys, export = open_command("export")
        online = param_position(export, "online")
        step = move(0, online)

        # Once: --online.
        first = [*keys, *step, "enter", *run_row(export, after=online), "x", "q"]
        assert drive(first)[1] == [["export", "--online"]]
        # Twice: --offline.
        second = [*keys, *step, "enter", "enter", *run_row(export, after=online), "x", "q"]
        assert drive(second)[1] == [["export", "--offline"]]
        # Three times: back to not set.
        third = [*keys, *step, *["enter"] * 3, *run_row(export, after=online), "x", "q"]
        assert drive(third)[1] == [["export"]]

    def test_backspace_clears_a_value(self) -> None:
        keys, export = open_command("export")
        output = param_position(export, "output")
        keys += [*move(0, output), "enter", "backspace"]
        keys += [*run_row(export, after=output), "x", "q"]
        _terminal, calls = drive(keys, ["out.csv"])
        assert calls == [["export"]]

    def test_the_form_shows_the_command_as_it_is_being_built(self) -> None:
        keys, export = open_command("export")
        output = param_position(export, "output")
        keys += [*move(0, output), "enter", "q"]
        terminal, _ = drive(keys, ["report.csv"])
        assert "discoverynow export --output report.csv" in terminal.last_screen

    def test_the_form_describes_the_option_under_the_cursor(self) -> None:
        keys, _ = open_command("export")
        terminal, _calls = drive([*keys, "q"])
        assert "File to write." in terminal.last_screen
        assert "Accepts:" in terminal.last_screen

    def test_it_will_not_run_until_the_required_values_are_given(self) -> None:
        keys, rename = open_command("devices", "rename")
        keys += [*run_row(rename, after=0), "q"]
        terminal, calls = drive(keys)
        assert calls == []
        assert "Needed first" in terminal.last_screen
        assert "SELECTOR" in terminal.last_screen

    def test_a_command_with_positional_arguments_runs_once_they_are_given(self) -> None:
        keys, rename = open_command("devices", "rename")
        keys += ["enter", *move(0, 1), "enter"]
        keys += [*run_row(rename, after=1), "x", "q"]
        _terminal, calls = drive(keys, ["192.168.1.5", "Printer"])
        assert calls == [["devices", "rename", "192.168.1.5", "Printer"]]

    def test_a_failed_command_says_so(self) -> None:
        keys, _ = open_command("interfaces")
        terminal, calls = drive([*keys, "enter", "x", "q"], code=3)
        assert calls == [["interfaces"]]
        assert "exit code 3" in terminal.everything

    def test_a_successful_command_says_so(self) -> None:
        keys, _ = open_command("interfaces")
        terminal, _calls = drive([*keys, "enter", "x", "q"])
        assert "Done." in terminal.everything

    def test_help_for_a_command_is_one_row_away(self) -> None:
        keys, scan = open_command("scan")
        keys += [*move(0, len(scan.params) + 1), "enter", "x", "q"]
        _terminal, calls = drive(keys)
        assert calls == [["scan", "--help"]]

    def test_a_command_remembers_what_was_set_when_it_is_opened_again(self) -> None:
        keys, scan = open_command("scan")
        no_dns = param_position(scan, "no_dns")
        keys += [*move(0, no_dns), "enter", "esc"]
        keys += [*move(position(ROOT, "scan"), position(ROOT, "scan")), "enter", "q"]
        terminal, _calls = drive(keys)
        assert re.search(r"--no-dns\s+on", terminal.last_screen)

    def test_the_program_wide_option_is_added_to_every_command(self) -> None:
        count = len(ROOT.children)
        keys = ["down"] * count + ["enter", "enter", "esc"]  # Global options, set --config
        keys += ["up"] * (count - position(ROOT, "status")) + ["enter"]
        keys += [*run_row(child(ROOT, "status"), after=0), "x", "q"]
        _terminal, calls = drive(keys, ["settings.toml"])
        assert calls == [["--config", "settings.toml", "status"]]


# ---------------------------------------------------------------------------
# Against the real command line
# ---------------------------------------------------------------------------


class TestRealRunner:
    def test_runs_a_real_command_and_reports_success(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert menu.make_runner(GROUP)(["--version"]) == 0
        assert "Discovery Now" in capsys.readouterr().out

    def test_a_command_that_fails_reports_its_status_without_closing_the_menu(self) -> None:
        assert menu.make_runner(GROUP)(["devices", "show", "no-such-device"]) == 1

    def test_a_usage_error_reports_status_two(self) -> None:
        assert menu.make_runner(GROUP)(["scan", "--no-such-option"]) == 2

    def test_the_menu_runs_a_real_command_end_to_end(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        keys, status = open_command("status")
        terminal = FakeTerminal([*keys, *run_row(status, after=0), "x", "q"])
        menu.Menu(ROOT, GLOBALS, terminal=terminal, runner=menu.make_runner(GROUP)).run()
        assert "Devices known" in capsys.readouterr().out


def test_the_command_refuses_to_run_without_a_terminal() -> None:
    result = runner.invoke(app, ["menu"])
    assert result.exit_code == 1
    assert "interactive terminal" in result.output
