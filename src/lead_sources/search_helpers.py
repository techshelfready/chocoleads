from __future__ import annotations

from typing import List, Dict
from ddgs import DDGS


def ddg_text(query: str, max_results: int = 10) -> List[Dict]:
    return list(DDGS(timeout=12).text(query, max_results=max_results, region="us-en", backend="auto"))


def run_queries(queries: list[str], max_results_per_query: int = 10) -> list[Dict]:
    merged: list[Dict] = []
    seen: set[str] = set()
    failures = 0
    for q in queries:
        try:
            results = ddg_text(q, max_results=max_results_per_query)
        except Exception:
            failures += 1
            results = []
        for r in results:
            u = (r.get("href") or r.get("url") or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            merged.append(r)
    if queries and failures == len(queries):
        raise RuntimeError("Search provider is unavailable.")
    return merged
