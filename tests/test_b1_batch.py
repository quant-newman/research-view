"""B1 批量结构化(2026-08-24 降本批#2):逐条→整批,省的是调用数,冒的险是**批内错位**。

钉死一件事:回写严格按 LLM 回的序号 i 对齐,任何对不上的情形(越界/重复/缺 i/条数不足)
一律丢弃该条,让它 llm_done 保持 false 下档重跑——绝不按数组位置猜。错位回写会把 A 条
的数字/公司钉到 B 条头上,那是事实层幻觉(红线),比少写一条严重得多。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from research_view import structure as S  # noqa: E402

ROWS = [(101, "A公司存储涨价", "正文A"), (102, "B公司扩产", "正文B"), (103, "C公司中标", None)]


def _item(i, one_line, ticker):
    return {"i": i, "sentiment": "中性", "event_type": "公告", "one_line": one_line,
            "summary": f"{one_line}的摘要", "is_chain_relevant": True, "tickers": [ticker]}


def test_align_by_index_not_position(monkeypatch):
    """LLM 乱序返回也必须按 i 归位,不能按数组位置。"""
    monkeypatch.setattr(S.llm, "chat_json", lambda *a, **k: {"items": [
        _item(2, "C一句话", "C公司"), _item(0, "A一句话", "A公司"), _item(1, "B一句话", "B公司")]})
    out = S._run_batch(ROWS)
    assert [r[0] for r in out] == [101, 102, 103]
    assert [r[3] for r in out] == ["A一句话", "B一句话", "C一句话"]
    assert [r[6] for r in out] == [["A公司"], ["B公司"], ["C公司"]]


@pytest.mark.parametrize("items,kept", [
    ([_item(0, "A", "A公司"), _item(9, "野", "野公司")], [101]),           # i 越界 → 丢
    ([_item(0, "A", "A公司"), _item(0, "重", "重公司")], [101]),           # i 重复 → 只认第一个
    ([_item(0, "A", "A公司"), {"one_line": "无序号"}], [101]),             # 缺 i → 丢
    ([_item(1, "B", "B公司")], [102]),                                     # 只回一条 → 只写一条
    ([], []),                                                              # 全空 → 一条都不写
])
def test_misaligned_items_are_dropped_not_guessed(monkeypatch, items, kept):
    monkeypatch.setattr(S.llm, "chat_json", lambda *a, **k: {"items": items})
    assert [r[0] for r in S._run_batch(ROWS)] == kept


def test_batch_failure_degrades_to_one_by_one(monkeypatch):
    """整批失败(可能是某条正文有毒而非网络)必须拆成逐条,否则该批永远卡在队列里。"""
    calls = []

    def fake(system, user, **k):
        calls.append(user)
        if "【本批 1 条新闻】" not in user:
            raise RuntimeError("批量炸了")
        if "正文B" in user:
            raise RuntimeError("B 条本身有毒")
        return {"items": [_item(0, "单条", "X公司")]}

    monkeypatch.setattr(S.llm, "chat_json", fake)
    out = S._run_batch(ROWS)
    assert len(calls) == 4                      # 1 次批量 + 3 次逐条
    assert [r[0] for r in out] == [101, 103]    # 有毒的 102 不回写,下档重跑


def test_prompt_numbers_each_item_and_keeps_rules_as_prefix():
    p = S._prompt([("标题一", "正文一"), ("标题二", None)])
    assert p.startswith(S.RULES)                # 规则块必须在最前:前缀缓存的命中前提
    assert "### 0" in p and "### 1" in p
    assert "标题:标题二" in p and p.count("正文(截断):") == 1


def test_run_structure_chunks_and_counts_calls(monkeypatch):
    rows = [(i, f"标题{i}", None) for i in range(20)]
    monkeypatch.setattr(S.db, "rv_conn", None, raising=False)
    seen = []

    def fake_batch(chunk):
        seen.append(len(chunk))
        return [S._row(r, _item(0, "x", "X")) for r in chunk]

    monkeypatch.setattr(S, "_run_batch", fake_batch)
    monkeypatch.setattr(S, "_fetch", lambda limit: rows)
    monkeypatch.setattr(S, "_writeback", lambda results: None)
    out = S.run_structure(batch=8)
    assert sorted(seen) == [4, 8, 8] and out["calls"] == 3 and out["structured"] == 20
