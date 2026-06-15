# aiase_contract.py — 評分器與 run_dev.py 共用的比對核心（學生可見，single source of truth）
#
# 比對邏輯只有這一份。評分器（staff-only，不在本 repo）import 同一支 aiase_contract，
# 因此你本地 run_dev.py 的 pass/fail 等同評分器的判定——但你看不到 hidden test、
# perturbation 與 reference 答案。
#
# ⚠️ 評分器專屬內容（hidden test / perturbation / reference / judge prompt）不得進入本檔。
import os
import json
import sqlite3
from collections import Counter


def resolve_result_path(default_name: str = "aiase_result.json") -> str:
    """結果檔路徑：優先環境變數 AIASE_RESULT_PATH，否則工作目錄下的 default_name。"""
    return os.environ.get("AIASE_RESULT_PATH") or os.path.join(os.getcwd(), default_name)


def read_result(path: str):
    """讀結果檔；不存在或非合法 JSON object 回 None（= 該題未產出）。"""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def validate_basic_schema(obj: dict, task_id: str):
    """Basic Track schema：task_id 一致、sql 為非空字串、confidence 在 0..1。回 (ok, reason)。"""
    if not isinstance(obj, dict):
        return False, "result is not an object"
    if obj.get("task_id") != task_id:
        return False, "task_id mismatch"
    if not isinstance(obj.get("sql"), str) or not obj["sql"].strip():
        return False, "missing/empty sql"
    c = obj.get("confidence", 0.5)
    if isinstance(c, bool) or not isinstance(c, (int, float)) or not (0.0 <= float(c) <= 1.0):
        return False, "confidence out of range"
    return True, ""


def bag_equal(rows_a, rows_b) -> bool:
    """order-insensitive multiset 比對：列順序不計、欄位順序不計、重複列次數計入。"""
    def norm(rows):
        return Counter(tuple(sorted(repr(x) for x in r)) for r in rows)
    return norm(rows_a) == norm(rows_b)


def run_sql(db_path: str, sql: str):
    """在 sqlite db 上執行 SQL 取得結果集（list of tuple），供 bag_equal 比對。

    語法/執行錯誤會 raise sqlite3.Error，由呼叫端轉成該題 fail。
    """
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()
