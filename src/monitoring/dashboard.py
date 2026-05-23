import asyncio
import logging
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

logger = logging.getLogger("monitoring.dashboard")


class CliDashboard:
    def __init__(self, system_refresh_func, refresh_interval: float = 2.0):
        self._health_fn = system_refresh_func
        self._interval = refresh_interval
        self._console = Console()
        self._running = False

    async def run(self) -> None:
        self._running = True
        with Live(console=self._console, refresh_per_second=4, screen=True) as live:
            while self._running:
                try:
                    health = await self._health_fn()
                    layout = self._build_layout(health)
                    live.update(layout)
                    await asyncio.sleep(self._interval)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Dashboard error: %s", e)
                    await asyncio.sleep(self._interval)

    def stop(self) -> None:
        self._running = False

    def _build_layout(self, health: dict[str, Any]) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )
        layout["header"].update(Panel("Trading System Dashboard", style="bold cyan"))
        layout["footer"].update(Panel("[dim]Ctrl+C to exit[/dim]", style="dim"))

        body = Layout()
        body.split_row(
            Layout(name="agents"),
            Layout(name="stats"),
        )

        agent_table = Table(title="Agent Status", box=None)
        agent_table.add_column("Agent", style="cyan")
        agent_table.add_column("Status", style="green")
        agent_table.add_column("Details")

        for name, status in health.items():
            st = status.get("status", "?")
            style = "green" if st == "running" else "red"
            details = []
            for k, v in status.items():
                if k not in ("agent", "status", "event_store", "subscribed_types"):
                    details.append(f"{k}={v}")
            agent_table.add_row(name, Text(st, style=style), ", ".join(details))

        body["agents"].update(Panel(agent_table))

        stats_table = Table(title="System Stats", box=None)
        stats_table.add_column("Metric", style="yellow")
        stats_table.add_column("Value")

        mi = health.get("market_intel", {})
        sg = health.get("strategy_gen", {})
        ex = health.get("execution", {})

        stats_table.add_row("Instruments", str(mi.get("instruments", "?")))
        stats_table.add_row("Signals", str(sg.get("strategies", "?")))
        stats_table.add_row("Open Orders", str(ex.get("open_orders", 0)))
        stats_table.add_row("Filled Orders", str(ex.get("filled_orders", 0)))
        stats_table.add_row("Paper Trading", str(ex.get("paper_trading", "?")))

        body["stats"].update(Panel(stats_table))
        layout["body"].update(body)
        return layout
