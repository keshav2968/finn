"""Check the LLM setup: keys present, configured models available, one live call each.

Usage (from the repo root):
    python scripts/llm_check.py          # keys + model lists (no tokens used)
    python scripts/llm_check.py --ping   # also one tiny JSON call per model in every chain
    python scripts/llm_check.py --usage  # token totals from data/seed/llm_usage.jsonl
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.router import LLMError, Router  # noqa: E402

PING_SCHEMA = {
    "type": "object",
    "required": ["ok", "capital"],
    "additionalProperties": False,
    "properties": {"ok": {"type": "boolean"}, "capital": {"type": "string"}},
}


def list_models(provider: dict, key: str) -> set[str]:
    base = provider["base_url"].rstrip("/")
    if provider["kind"] == "openai_compatible":
        r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
        r.raise_for_status()
        return {m["id"] for m in r.json().get("data", [])}
    r = requests.get(f"{base}/models", params={"pageSize": 1000}, headers={"x-goog-api-key": key}, timeout=20)
    r.raise_for_status()
    return {m["name"].split("/", 1)[-1] for m in r.json().get("models", [])}


def usage_report(path: Path) -> None:
    if not path.exists():
        print(f"No usage yet ({path})")
        return
    rows = collections.defaultdict(lambda: {"calls": 0, "cached": 0, "failed": 0, "in": 0, "out": 0})
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        r = rows[(rec["task"], f"{rec['provider']}/{rec['model']}")]
        r["calls"] += 1
        r["cached"] += bool(rec.get("cached"))
        r["failed"] += not rec.get("ok", True)
        r["in"] += rec.get("input_tokens", 0)
        r["out"] += rec.get("output_tokens", 0)
    print(f"{'task':<20}{'model':<36}{'calls':>6}{'cached':>8}{'failed':>8}{'tokens in':>11}{'tokens out':>11}")
    for (task, model), r in sorted(rows.items()):
        print(f"{task:<20}{model:<36}{r['calls']:>6}{r['cached']:>8}{r['failed']:>8}{r['in']:>11}{r['out']:>11}")
    print(f"Total tokens: {sum(r['in'] + r['out'] for r in rows.values()):,} · cost: Rs 0 (free tiers)")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser()
    p.add_argument("--ping", action="store_true")
    p.add_argument("--usage", action="store_true")
    args = p.parse_args(argv)
    router = Router.from_config()
    if args.usage:
        usage_report(router.usage_log)
        return 0

    problems = 0
    for name, provider in router.providers.items():
        env = provider.get("api_key_env")
        key = router.env.get(env or "")
        print(f"{name}: {env} {'found' if key else 'MISSING'}")
        if not key:
            problems += 1
            continue
        try:
            available = list_models(provider, key)
        except requests.RequestException as exc:
            print(f"  could not list models: {exc}")
            problems += 1
            continue
        wanted = sorted({e.model for t in router.tasks.values() for e in t["chain"] if e.provider == name})
        for model in wanted:
            ok = model in available
            problems += not ok
            print(f"  {'ok     ' if ok else 'MISSING'} {model}")

    if args.ping:
        for task, spec in router.tasks.items():
            for entry in spec["chain"]:
                try:
                    res = router.complete_json(
                        task, "You answer quiz questions.", 'Return JSON {"ok": true, "capital": <capital of India>}.',
                        PING_SCHEMA, label="llm_check", only=entry.key,
                    )
                    print(f"ping {task:<20}{entry.key:<36}ok  {res.data} ({res.input_tokens}+{res.output_tokens} tokens{', cached' if res.cached else ''})")
                except LLMError as exc:
                    problems += 1
                    print(f"ping {task:<20}{entry.key:<36}FAILED\n     {'; '.join(exc.attempts)[:500]}")
    print("All good." if problems == 0 else f"{problems} problem(s) above.")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
