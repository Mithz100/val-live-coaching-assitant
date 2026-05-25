"""
Developer debug dashboard.

Connects to the event service WebSocket endpoints and prints a live
terminal view of the semantic event stream, round state, patterns,
and player profile.

Run:
    python debug_dashboard.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime

import websockets

BASE = "ws://localhost:8200"

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
GREY   = "\033[90m"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _color_confidence(conf: float) -> str:
    if conf >= 0.8:
        return GREEN
    if conf >= 0.55:
        return YELLOW
    return RED


async def watch_channel(channel: str, handler) -> None:
    url = f"{BASE}/{channel}"
    while True:
        try:
            async with websockets.connect(url) as ws:
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        handler(data)
                    except Exception:
                        pass
        except Exception:
            await asyncio.sleep(2)


def on_semantic(data) -> None:
    ev  = data.get("event_type", "?")
    rnd = data.get("round_number", 0)
    conf = data.get("confidence", 0.0)
    expl = data.get("explanation", "")
    col = _color_confidence(conf)
    print(
        f"{GREY}[{_ts()}]{RESET} "
        f"{BOLD}{col}⚡ {ev:<35}{RESET} "
        f"R{rnd:02d}  conf={col}{conf:.2f}{RESET}  {GREY}{expl[:80]}{RESET}"
    )


def on_round_state(data) -> None:
    phase  = data.get("phase", "?")
    rnd    = data.get("round_number", 0)
    death  = data.get("death_count", 0)
    peeks  = data.get("solo_peek_count", 0)
    surv   = data.get("survival_time_s")
    surv_s = f"{surv:.0f}s" if surv else "--"
    print(
        f"{GREY}[{_ts()}]{RESET} "
        f"{CYAN}◉ ROUND STATE{RESET}  "
        f"R{rnd:02d}  phase={phase:<12}  deaths={death}  solo_peeks={peeks}  survival={surv_s}"
    )


def on_summary(data) -> None:
    rnd     = data.get("round_number", 0)
    econ    = data.get("economy_quality", "?")
    aggr    = data.get("aggression_score", 0.0)
    surv    = data.get("survival_time_seconds")
    surv_s  = f"{surv:.0f}s" if surv else "--"
    result  = data.get("result", "?")
    mistakes = data.get("major_mistakes", [])
    positives = data.get("positive_behaviors", [])

    col = GREEN if result == "VICTORY" else (RED if result == "DEFEAT" else YELLOW)
    print(f"\n{'─'*70}")
    print(
        f"{BOLD}📋 ROUND {rnd} SUMMARY{RESET}  "
        f"{col}{result}{RESET}  "
        f"econ={econ}  aggr={aggr:.2f}  surv={surv_s}"
    )
    if mistakes:
        print(f"  {RED}✗ Mistakes:{RESET} {', '.join(mistakes)}")
    if positives:
        print(f"  {GREEN}✓ Positive:{RESET} {', '.join(positives)}")
    print(f"{'─'*70}\n")


def on_pattern(data) -> None:
    if not isinstance(data, list):
        data = [data]
    for p in data:
        ptype = p.get("pattern_type", "?")
        occ   = p.get("occurrences", 0)
        conf  = p.get("confidence", 0.0)
        desc  = p.get("description", "")
        col = _color_confidence(conf)
        print(
            f"{GREY}[{_ts()}]{RESET} "
            f"{BOLD}{col}🔁 PATTERN: {ptype}{RESET}  "
            f"x{occ}  conf={conf:.2f}  {GREY}{desc[:70]}{RESET}"
        )


def on_profile(data) -> None:
    rounds  = data.get("rounds_tracked", 0)
    surv    = data.get("avg_survival_rate", 0.0)
    aggr    = data.get("avg_aggression_score", 0.0)
    econ    = data.get("avg_economy_discipline", 0.0)
    patterns = data.get("active_patterns", [])
    print(
        f"{GREY}[{_ts()}]{RESET} "
        f"👤 PROFILE  "
        f"rounds={rounds}  survival={surv:.2f}  aggr={aggr:.2f}  econ_disc={econ:.2f}  "
        f"patterns=[{','.join(patterns)}]"
    )


async def main() -> None:
    print(f"{BOLD}Valorant AI Coach — Debug Dashboard{RESET}")
    print(f"Connecting to {BASE} …\n")

    await asyncio.gather(
        watch_channel("semantic-events", on_semantic),
        watch_channel("round-state",    on_round_state),
        watch_channel("round-summary",  on_summary),
        watch_channel("patterns",       on_pattern),
        watch_channel("profile",        on_profile),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDashboard closed.")
