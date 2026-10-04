# -*- coding: utf-8 -*-
"""Count the answers the answer-relevance gate REPLACED, by day and lane (QA-trial plan 1.4).

BUG-1252: four of six "false declines" in tail N were not declines at all -- the lane had bound
and fetched the data and the gate deleted the answer. Nothing counted that, so the gate's
actions were invisible in every quality number. The orchestrator logs one line per replacement
(`_orchestrator._response_node`):

    [response] relevance gate replaced a sensor_data answer: OFF_TOPIC ...

This reads the container log over a window and tabulates those lines, so a weekly review can
put the gate's deletions beside the hand-read declines. It is a count of ACTIONS, not of
errors: the gate is right some of the time (tail N: at least two of four), and only a hand read
of the replaced answers says which.

    python scripts/count_gate_deletions.py --since 168h            # the last week
    python scripts/count_gate_deletions.py --since 24h --show       # print each line
"""
import argparse
import collections
import re
import subprocess
import sys

_LINE = re.compile(
    r"^(?P<day>\d{4}-\d{2}-\d{2}) \S+ .*relevance gate replaced a (?P<lane>\S+) answer: "
    r"(?P<verdict>[A-Z_]+)"
)


def _log(container: str, since: str) -> str:
    out = subprocess.run(
        ["docker", "logs", "--since", since, container],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (out.stdout or "") + (out.stderr or "")


def tabulate(text: str):
    """(by_day_lane, by_verdict, lines) from a log text."""
    by_day_lane = collections.Counter()
    by_verdict = collections.Counter()
    lines = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        by_day_lane[(m.group("day"), m.group("lane"))] += 1
        by_verdict[m.group("verdict")] += 1
        lines.append(line.strip())
    return by_day_lane, by_verdict, lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default="ontosage-orchestrator")
    ap.add_argument("--since", default="168h", help="docker logs --since value")
    ap.add_argument("--show", action="store_true", help="print every replacement line")
    args = ap.parse_args()
    by_day_lane, by_verdict, lines = tabulate(_log(args.container, args.since))
    print(f"relevance gate replacements in the last {args.since}: {len(lines)}")
    for (day, lane), n in sorted(by_day_lane.items()):
        print(f"  {day}  {lane:<14} {n}")
    if by_verdict:
        print("by verdict: " + ", ".join(f"{k}={v}" for k, v in by_verdict.most_common()))
    if args.show:
        for line in lines:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
