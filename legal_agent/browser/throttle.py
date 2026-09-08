"""1 回の質問（run）あたりの外部アクセス上限。利用規約配慮のため機械的な大量取得を防ぐ。"""
from __future__ import annotations

from collections import Counter


class BudgetExceeded(Exception):
    pass


class RunBudget:
    def __init__(self, max_searches_per_source: int, max_fetches: int):
        self.max_searches = max_searches_per_source
        self.max_fetches = max_fetches
        self.searches: Counter[str] = Counter()
        self.fetches = 0

    def take_search(self, source: str) -> None:
        if self.searches[source] >= self.max_searches:
            raise BudgetExceeded(
                f"{source} の検索回数がこの質問での上限（{self.max_searches} 回）に達しました。"
                "既に得た結果から回答するか、利用者に追加の質問として分けてもらってください。"
            )
        self.searches[source] += 1

    def take_fetch(self) -> None:
        if self.fetches >= self.max_fetches:
            raise BudgetExceeded(
                f"本文取得の回数がこの質問での上限（{self.max_fetches} 件）に達しました。"
                "既に読んだ内容で回答してください。"
            )
        self.fetches += 1
