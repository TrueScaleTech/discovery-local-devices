"""The ``discoverynow`` command line.

Every command that shows something can also print it as JSON, so the same tool
serves a person reading a table and a script reading a pipe.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from . import APP_NAME, __version__
from . import export as exporting
from .config import Settings, config_path, database_path
from .discovery import ScanReport, run_scan
from .models import Device, ScanOutcome
from .monitor import watch as watch_loop
from .net import TargetError, local_interfaces
from .render import (
    device_as_dict,
    device_detail,
    devices_table,
    event_as_dict,
    events_table,
    local_time,
    observation_as_dict,
    observations_table,
    summary_table,
)
from .store import Store

console = Console()
errors = Console(stderr=True)

EXIT_ERROR = 1
EXIT_FINDINGS = 3

app = typer.Typer(
    help=f"{APP_NAME}: discover, inventory and monitor the devices on your own network.",
    no_args_is_help=True,
    add_completion=False,
)
devices_app = typer.Typer(help="Inspect and annotate the devices in the inventory.")
config_app = typer.Typer(help="Show and create the configuration file.")
app.add_typer(devices_app, name="devices")
app.add_typer(config_app, name="config")


# -- shared helpers ----------------------------------------------------------


def _settings(ctx: typer.Context) -> Settings:
    settings = ctx.obj
    if not isinstance(settings, Settings):  # pragma: no cover - only if invoked oddly
        settings = Settings.load()
        ctx.obj = settings
    return settings


def _fail(message: str) -> None:
    """Report a problem on stderr and stop with a non-zero status."""
    errors.print(f"[bold red]Error:[/] {message}")
    raise typer.Exit(EXIT_ERROR)


def _new_window(settings: Settings) -> timedelta:
    return timedelta(days=settings.new_device_days)


def _emit_json(payload: Any) -> None:
    """Write JSON straight to stdout, unstyled, so it can be piped."""
    typer.echo(json.dumps(payload, indent=2, sort_keys=False))


def _require(store: Store, selector: str) -> Device:
    device = store.find(selector)
    if device is None:
        _fail(f"No single device matches {selector!r}. Try the number from `devices list`.")
        raise typer.Exit(EXIT_ERROR)  # pragma: no cover - _fail already exits
    return device


def _version(value: bool) -> None:
    if value:
        console.print(f"{APP_NAME} {__version__}")
        raise typer.Exit


@app.callback()
def main_options(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Configuration file to use.", show_default=False),
    ] = None,
    _show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Load the configuration once, for whichever command runs."""
    ctx.obj = Settings.load(config)


# -- scanning ----------------------------------------------------------------


def _run_with_progress(settings: Settings, *, show: bool) -> ScanReport:
    """Run a scan, with a progress bar when there is a terminal to draw it on."""
    if not show:
        return run_scan(settings)

    # The default spinner is made of Braille characters, which a legacy Windows code
    # page cannot encode: scanning with output sent to NUL used to crash on it. A
    # plain ASCII spinner is used whenever the console cannot write them.
    spinner = "line" if console.options.ascii_only else "dots"
    columns = (
        SpinnerColumn(spinner),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
    )
    with Progress(*columns, console=console, transient=True) as progress:
        task = progress.add_task("preparing", total=None)

        def report(stage: str, done: int, total: int) -> None:
            progress.update(task, description=stage, completed=done, total=total)

        return run_scan(settings, progress=report)


def _describe(report: ScanReport) -> str:
    networks = ", ".join(str(network) for network in report.networks)
    return (
        f"{report.found} device(s) on {networks} "
        f"({report.addresses_probed} addresses probed in {report.duration:.1f}s)"
    )


def _print_outcome(outcome: ScanOutcome) -> None:
    """Say what changed, and nothing when nothing did."""
    for device in outcome.discovered:
        console.print(f"[bold magenta]new[/]      {device.ip}  {device.name}")
    for device in outcome.back_online:
        console.print(f"[green]online[/]   {device.ip}  {device.name}")
    for device in outcome.went_offline:
        console.print(f"[red]offline[/]  {device.ip}  {device.name}")
    for device, kind, detail in outcome.changed:
        console.print(f"[yellow]{kind.value}[/]  {device.ip}  {device.name}  {detail}")


@app.command()
def scan(
    ctx: typer.Context,
    subnet: Annotated[
        list[str] | None,
        typer.Option("--subnet", "-s", help="Subnet to scan, e.g. 192.168.1.0/24. Repeatable."),
    ] = None,
    timeout: Annotated[float | None, typer.Option(help="Seconds to wait per probe.")] = None,
    workers: Annotated[int | None, typer.Option(help="Parallel probes.")] = None,
    no_dns: Annotated[bool, typer.Option("--no-dns", help="Skip hostname lookups.")] = False,
    no_store: Annotated[
        bool, typer.Option("--no-store", help="Do not write to the inventory.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")] = False,
    fail_on_new: Annotated[
        bool,
        typer.Option("--fail-on-new", help="Exit with status 3 if a new device appeared."),
    ] = False,
) -> None:
    """Scan the network once and record what is there."""
    settings = _settings(ctx)
    if subnet:
        settings.subnets = list(subnet)
    if timeout is not None:
        settings.timeout = timeout
    if workers is not None:
        settings.workers = workers
    if no_dns:
        settings.resolve_hostnames = False

    try:
        report = _run_with_progress(settings, show=not as_json and console.is_terminal)
    except TargetError as error:
        _fail(str(error))
        return

    outcome = ScanOutcome()
    if not no_store:
        with Store() as store:
            outcome = store.record_scan(report.observations, offline_after=settings.offline_after)
            store.record_scan_run(
                networks=[str(network) for network in report.networks],
                probed=report.addresses_probed,
                found=report.found,
                duration=report.duration,
            )

    if as_json:
        _emit_json(
            {
                "networks": [str(network) for network in report.networks],
                "addresses_probed": report.addresses_probed,
                "duration_seconds": round(report.duration, 3),
                "devices": [observation_as_dict(item) for item in report.observations],
                "new_devices": [
                    device_as_dict(device, new_within=_new_window(settings))
                    for device in outcome.discovered
                ],
            }
        )
    else:
        console.print(observations_table(report.observations, title=_describe(report)))
        if outcome.has_news:
            console.print()
            _print_outcome(outcome)

    if fail_on_new and outcome.discovered:
        raise typer.Exit(EXIT_FINDINGS)


@app.command()
def watch(
    ctx: typer.Context,
    interval: Annotated[
        int | None, typer.Option("--interval", "-i", help="Seconds between scans.")
    ] = None,
    rounds: Annotated[
        int | None, typer.Option(help="Stop after this many scans. Default: run until stopped.")
    ] = None,
) -> None:
    """Keep scanning on a schedule and report every change as it happens."""
    settings = _settings(ctx)
    if interval is not None:
        settings.watch_interval = interval

    console.print(
        f"Watching every {settings.watch_interval}s. "
        f"A device is called offline after {settings.offline_after} missed scans. "
        "Press Ctrl+C to stop."
    )

    def on_round(report: ScanReport, outcome: ScanOutcome) -> None:
        stamp = local_time(datetime.now().astimezone())
        console.print(f"[dim]{stamp}[/]  {report.found} online  ({report.duration:.1f}s)")
        _print_outcome(outcome)

    try:
        with Store() as store:
            completed = watch_loop(settings, store, on_round=on_round, rounds=rounds)
    except TargetError as error:
        _fail(str(error))
        return
    except KeyboardInterrupt:
        console.print("\nStopped.")
        return
    console.print(f"Finished after {completed} scan(s).")


@app.command()
def status(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")] = False,
) -> None:
    """Show the headline numbers for the inventory."""
    settings = _settings(ctx)
    with Store() as store:
        counts = store.summary(new_within=_new_window(settings))
    if as_json:
        _emit_json(counts)
        return
    console.print(summary_table(counts))
    console.print(f"\n[dim]Inventory: {database_path()}[/]")


@app.command()
def interfaces() -> None:
    """List the local interfaces and the subnets a scan would cover by default."""
    found = local_interfaces()
    if not found:
        console.print("No active IPv4 interface found.")
        return
    for interface in found:
        console.print(f"{interface.name}: {interface.address}  ->  {interface.network}")


@app.command()
def events(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many entries to show.")] = 30,
    device: Annotated[str | None, typer.Option("--device", "-d", help="Only this device.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")] = False,
) -> None:
    """Show what has happened on the network lately."""
    _settings(ctx)
    with Store() as store:
        device_id = _require(store, device).id if device else None
        history = store.events(device_id=device_id, limit=limit)
        names = {item.id: item.name for item in store.devices()}
    if as_json:
        _emit_json([event_as_dict(event) for event in history])
        return
    if not history:
        console.print("Nothing recorded yet. Run `discoverynow scan` first.")
        return
    console.print(events_table(history, names, title="Recent events"))


@app.command("export")
def export_devices(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="File to write. Without it, print to the terminal."),
    ] = None,
    fmt: Annotated[
        exporting.ExportFormat | None,
        typer.Option(
            "--format", "-f", help="csv or json. By default taken from the file name, else csv."
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite the file if it already exists.")
    ] = False,
    online: Annotated[
        bool | None, typer.Option("--online/--offline", help="Only devices in this state.")
    ] = None,
    new: Annotated[bool, typer.Option("--new", help="Only devices first seen recently.")] = False,
    unapproved: Annotated[
        bool, typer.Option("--unapproved", help="Only devices you have not approved.")
    ] = False,
    redact: Annotated[
        bool,
        typer.Option(
            "--redact",
            help="Hide the unique half of each MAC, and every hostname, label and note.",
        ),
    ] = False,
) -> None:
    """Write the device list to a CSV or JSON file, or print it.

    The inventory holds hardware addresses and names that identify people. Use
    --redact before sharing an export outside your own machine.
    """
    settings = _settings(ctx)
    window = _new_window(settings)

    chosen = fmt
    if chosen is None:
        is_json = output is not None and output.suffix.lower() == ".json"
        chosen = exporting.ExportFormat.JSON if is_json else exporting.ExportFormat.CSV

    if output is not None and output.exists() and not force:
        _fail(f"{output} already exists. Pass --force to overwrite it.")

    with Store() as store:
        found = store.devices(
            online=online,
            approved=False if unapproved else None,
            new_within=window if new else None,
        )

    text = exporting.render(exporting.rows(found, new_within=window, redact=redact), chosen)

    if output is None:
        # Nothing but the data on stdout, so it can be piped or redirected.
        typer.echo(text, nl=False)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    # A byte-order mark makes Excel on Windows read accents correctly; JSON has none.
    encoding = "utf-8-sig" if chosen is exporting.ExportFormat.CSV else "utf-8"
    with output.open("w", encoding=encoding, newline="") as handle:
        handle.write(text)
    note = " Hostnames, labels, notes and MAC endings are hidden." if redact else ""
    console.print(f"Exported {len(found)} device(s) to {output}.{note}")


# -- devices -----------------------------------------------------------------


@devices_app.command("list")
def devices_list(
    ctx: typer.Context,
    online: Annotated[
        bool | None, typer.Option("--online/--offline", help="Only devices in this state.")
    ] = None,
    new: Annotated[bool, typer.Option("--new", help="Only devices first seen recently.")] = False,
    unapproved: Annotated[
        bool, typer.Option("--unapproved", help="Only devices you have not approved.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")] = False,
) -> None:
    """List the devices in the inventory."""
    settings = _settings(ctx)
    window = _new_window(settings)
    with Store() as store:
        found = store.devices(
            online=online,
            approved=False if unapproved else None,
            new_within=window if new else None,
        )
    if as_json:
        _emit_json([device_as_dict(device, new_within=window) for device in found])
        return
    if not found:
        console.print("No devices match. Run `discoverynow scan` to populate the inventory.")
        return
    console.print(devices_table(found, new_within=window, title=f"{len(found)} device(s)"))


@devices_app.command("show")
def devices_show(
    ctx: typer.Context,
    selector: Annotated[str, typer.Argument(help="Number, IP, MAC or name.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")] = False,
) -> None:
    """Show everything known about one device."""
    settings = _settings(ctx)
    window = _new_window(settings)
    with Store() as store:
        device = _require(store, selector)
        history = store.events(device_id=device.id, limit=15)
    if as_json:
        payload = device_as_dict(device, new_within=window)
        payload["events"] = [event_as_dict(event) for event in history]
        _emit_json(payload)
        return
    console.print(device_detail(device, history, new_within=window))


@devices_app.command("rename")
def devices_rename(
    ctx: typer.Context,
    selector: Annotated[str, typer.Argument(help="Number, IP, MAC or name.")],
    label: Annotated[str, typer.Argument(help="The name to show from now on.")],
) -> None:
    """Give a device a name you will recognise."""
    _settings(ctx)
    with Store() as store:
        device = _require(store, selector)
        store.set_label(device.id, label)
    console.print(f"{device.ip} is now [bold]{label}[/].")


@devices_app.command("note")
def devices_note(
    ctx: typer.Context,
    selector: Annotated[str, typer.Argument(help="Number, IP, MAC or name.")],
    text: Annotated[str, typer.Argument(help="The note to attach.")],
) -> None:
    """Attach a note to a device."""
    _settings(ctx)
    with Store() as store:
        device = _require(store, selector)
        store.set_notes(device.id, text)
    console.print(f"Note saved for {device.name}.")


@devices_app.command("approve")
def devices_approve(
    ctx: typer.Context,
    selector: Annotated[str, typer.Argument(help="Number, IP, MAC or name.")],
    revoke: Annotated[
        bool, typer.Option("--revoke", help="Withdraw approval instead of granting it.")
    ] = False,
) -> None:
    """Mark a device as one that belongs here.

    Approving is how the inventory separates "this is mine" from "I have never
    looked at this": anything unapproved stays flagged in the listing.
    """
    _settings(ctx)
    with Store() as store:
        device = _require(store, selector)
        store.set_approved(device.id, not revoke)
    verb = "no longer approved" if revoke else "approved"
    console.print(f"{device.name} is {verb}.")


@devices_app.command("forget")
def devices_forget(
    ctx: typer.Context,
    selector: Annotated[str, typer.Argument(help="Number, IP, MAC or name.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
) -> None:
    """Remove a device and its history from the inventory."""
    _settings(ctx)
    with Store() as store:
        device = _require(store, selector)
        if not yes:
            typer.confirm(f"Delete {device.name} ({device.ip}) and its history?", abort=True)
        store.forget(device.id)
    console.print(f"{device.name} removed. It will reappear if it is still on the network.")


# -- configuration -----------------------------------------------------------


@config_app.command("path")
def config_show_path() -> None:
    """Print where the configuration file lives."""
    console.print(str(config_path()))


@config_app.command("init")
def config_init() -> None:
    """Write a commented configuration file, if there is not one already."""
    settings = Settings()
    target = settings.write_default()
    console.print(f"Configuration at {target}")


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """Print the settings currently in effect."""
    settings = _settings(ctx)
    _emit_json(
        {
            "config_file": str(config_path()),
            "database": str(database_path()),
            "subnets": settings.subnets or "auto-detected",
            "allow_public_ranges": settings.allow_public_ranges,
            "workers": settings.workers,
            "timeout": settings.timeout,
            "ports": settings.ports,
            "resolve_hostnames": settings.resolve_hostnames,
            "offline_after": settings.offline_after,
            "new_device_days": settings.new_device_days,
            "watch_interval": settings.watch_interval,
        }
    )


def main() -> None:
    """Entry point for the ``discoverynow`` command."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
