"""Small load test for the gateway (owner: M5).

Sends a mix of clean, toxic and spam comments concurrently and prints latency
percentiles and the verdict mix. Used to demo autoscaling (HPA) and to compare
stable vs canary.

Run:  python scripts/load_test.py --url http://localhost:8000 --requests 2000 --concurrency 20
      python scripts/load_test.py --url http://<VM_IP> --canary   # only hit the canary
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
from collections import Counter

import httpx

COMMENTS = [
    "Thanks for sharing, this was a helpful read",
    "I disagree with the author but respect the argument",
    "You are a complete idiot and should shut up",
    "Check out my channel for free giveaways http://bit.ly/123",
    "Absolute L take, touch grass you npc",
    "Muy buen articulo, gracias por compartir",
    "The council should publish the budget before the vote",
]


async def worker(client, url, queue, latencies, verdicts, errors, headers):
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        start = time.perf_counter()
        try:
            r = await client.post(f"{url}/moderate", json={"text": random.choice(COMMENTS)}, headers=headers)
            r.raise_for_status()
            body = r.json()
            verdicts[(body["variant"], body["verdict"])] += 1
        except httpx.HTTPError:
            errors.append(1)
        latencies.append(time.perf_counter() - start)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--canary", action="store_true", help="send X-Canary: always")
    args = parser.parse_args()

    queue: asyncio.Queue = asyncio.Queue()
    for _ in range(args.requests):
        queue.put_nowait(1)
    latencies, verdicts, errors = [], Counter(), []
    headers = {"X-Canary": "always"} if args.canary else {}
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=10) as client:
        await asyncio.gather(*(worker(client, args.url, queue, latencies, verdicts, errors, headers)
                               for _ in range(args.concurrency)))
    elapsed = time.perf_counter() - start

    q = statistics.quantiles(latencies, n=100)
    print(f"{args.requests} requests in {elapsed:.1f}s ({args.requests / elapsed:.0f} req/s), {len(errors)} errors")
    print(f"latency p50 {q[49] * 1000:.0f} ms   p95 {q[94] * 1000:.0f} ms   p99 {q[98] * 1000:.0f} ms")
    for (variant, verdict), n in sorted(verdicts.items()):
        print(f"  {variant:7s} {verdict:7s} {n}")


if __name__ == "__main__":
    asyncio.run(main())
