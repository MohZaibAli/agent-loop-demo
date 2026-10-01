"""Start N runs against a running API and print each lane's result.

    uv run python scripts/parallel_demo.py --base http://localhost:8000 --count 3
Add --real with X-Demo-Key in DEMO_KEY to request real-provider runs (budget guards apply).
"""

import argparse
import asyncio
import json
import os

import httpx


async def follow(client: httpx.AsyncClient, run_id: str) -> dict:
    final = {}
    async with client.stream("GET", f"/runs/{run_id}/events") as resp:
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            if ev["type"] == "tool_call":
                print(f"[{run_id}] {ev['name']:<10} {json.dumps(ev['arguments'])[:80]}")
            elif ev["type"] == "run_finished":
                final = ev
    return final


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("AGENT_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--task", default="Fix the parser so all tests pass")
    ap.add_argument("--real", action="store_true", help="send X-Demo-Key from DEMO_KEY")
    args = ap.parse_args()
    headers = {"X-Demo-Key": os.environ["DEMO_KEY"]} if args.real else {}
    async with httpx.AsyncClient(base_url=args.base, timeout=None, headers=headers) as client:
        r = await client.post("/runs/batch", json={"task": args.task, "count": args.count})
        r.raise_for_status()
        ids = r.json()["run_ids"]
        print(f"provider={r.json()['provider']} runs={ids}")
        finals = await asyncio.gather(*[follow(client, i) for i in ids])
        for f in finals:
            print(f"{f['sandbox_id']}  {f['status']:<9} tests={f['tests_passed']}/{(f['tests_passed'] or 0) + (f['tests_failed'] or 0)}"
                  f"  turns={f['turns']}  cost=${f['cost']:.4f}")
        budget = (await client.get("/budget")).json()
        print(f"budget: spent=${budget['spent']:.4f} remaining=${budget['remaining']:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
