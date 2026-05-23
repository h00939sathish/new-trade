#!/usr/bin/env python3
"""Run a trading agent from the command line.

Usage:
    python scripts/run_agent.py market_intel
    python scripts/run_agent.py strategy_gen
    python scripts/run_agent.py risk_mgmt
    python scripts/run_agent.py execution
    python scripts/run_agent.py all
"""

import asyncio
import logging
import signal
import sys
from typing import NoReturn

from src.agents import (
    ExecutionAgent,
    MarketIntelAgent,
    RiskManagementAgent,
    StrategyGenAgent,
)

AGENTS = {
    "market_intel": MarketIntelAgent,
    "strategy_gen": StrategyGenAgent,
    "risk_mgmt": RiskManagementAgent,
    "execution": ExecutionAgent,
}


async def run_agent(name: str) -> None:
    agent_class = AGENTS.get(name)
    if agent_class is None:
        print(f"Unknown agent: {name}")
        print(f"Available: {', '.join(AGENTS.keys())}")
        sys.exit(1)

    agent = agent_class()
    loop = asyncio.get_event_loop()

    def shutdown() -> None:
        print(f"\nShutting down {name}...")
        asyncio.create_task(agent.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            pass

    try:
        await agent.start()
        print(f"{name} agent is running. Press Ctrl+C to stop.")
        await agent.run_forever()
    except asyncio.CancelledError:
        pass
    finally:
        await agent.stop()


async def run_all() -> None:
    agents = [cls() for cls in AGENTS.values()]
    tasks = []
    for agent in agents:
        await agent.start()
        tasks.append(asyncio.create_task(agent.run_forever()))
    print(f"All {len(agents)} agents running. Press Ctrl+C to stop.")
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for agent in agents:
            await agent.stop()


def main() -> NoReturn:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if len(sys.argv) < 2:
        print("Usage: python scripts/run_agent.py <agent_name|all>")
        print(f"Agents: {', '.join(AGENTS.keys())}, all")
        sys.exit(1)

    name = sys.argv[1]
    if name == "all":
        asyncio.run(run_all())
    else:
        asyncio.run(run_agent(name))

    sys.exit(0)


if __name__ == "__main__":
    main()
