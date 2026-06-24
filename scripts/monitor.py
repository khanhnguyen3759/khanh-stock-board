"""Monitor sống trên VM — chạy định kỳ (systemd timer, ~15 phút/lần).

Mục tiêu: board LUÔN tươi để liếc là biết hệ thống còn sống & đúng.
  - Trong giờ GD (T2–T6, 9:00–15:00): mark-to-market -> equity nhảy sống động.
  - Sau đóng cửa (>=15:30, T2–T6): chạy quyết định MUA/BÁN 1 lần/ngày.
  - Luôn có 1 "nhịp tim" mỗi ngày (kể cả cuối tuần) -> không bao giờ im ru.

Chính sách push (tránh spam commit):
  - Có lệnh mới -> push.
  - Lần đầu trong ngày (sau 8:00) -> push nhịp tim (đảm bảo >=1 commit/ngày).
  - Đang giờ GD -> làm tươi equity tối đa mỗi ~1 giờ.
KHÔNG secret, chỉ dữ liệu giá công khai.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

from engine.feed import DataFeed
from engine.paper import Config, run_tick
from engine.store import Store
from scripts.run import BOARD_JSON, build_snapshot

VN = ZoneInfo("Asia/Ho_Chi_Minh")
MARKET_REFRESH_SEC = 55 * 60


def market_status(now: datetime) -> tuple[str, bool, bool]:
    """Trả (mô tả, là_ngày_GD, đang_mở_cửa)."""
    is_weekday = now.weekday() < 5
    hm = now.hour * 60 + now.minute
    is_open = is_weekday and 9 * 60 <= hm <= 15 * 60
    if not is_weekday:
        return "Nghỉ cuối tuần", False, False
    return ("Đang mở cửa" if is_open else "Đã đóng cửa"), True, is_open


def git_push(repo_msg: str) -> bool:
    subprocess.run(["git", "add", "data/paper.db", "docs/data.json"], check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode
    if staged == 0:
        return False  # không có thay đổi
    subprocess.run(["git", "commit", "-q", "-m", repo_msg], check=True)
    subprocess.run(["git", "push", "-q"], check=True)
    return True


def main() -> int:
    now = datetime.now(tz=VN)
    today = now.date().isoformat()
    status, is_weekday, is_open = market_status(now)

    cfg = Config.load()
    feed = DataFeed()
    with Store(cfg.db_path) as store:
        store.ensure_initialized(cfg.paper_capital)

        # quyết định MUA/BÁN: 1 lần/ngày, sau 15:30 ngày GD
        traded = False
        after_close = now.hour > 15 or (now.hour == 15 and now.minute >= 30)
        if is_weekday and after_close and store.get_meta("decision_day") != today:
            events = run_tick(cfg, store, feed)
            traded = any(e.get("action") in ("buy", "sell") and e.get("ok")
                         and not e.get("skipped") for e in events)
            store.set_meta("decision_day", today)
        else:
            events = []

        # mark-to-market + ghi điểm equity hôm nay + dựng snapshot
        snap = build_snapshot(cfg, store, feed, events)
        snap["market_status"] = status
        snap["checked_at"] = now.isoformat(timespec="seconds")
        BOARD_JSON.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

        # chính sách push
        reason = None
        if traded:
            reason = "lệnh mới"
        elif store.get_meta("last_push_day") != today and now.hour >= 8:
            reason = "nhịp tim ngày"
        elif is_open:
            last = store.get_meta("last_push_ts")
            if last is None or (now - datetime.fromisoformat(last)).total_seconds() >= MARKET_REFRESH_SEC:
                reason = "làm tươi equity"

        pushed = False
        if reason:
            msg = f"Monitor {today} {now:%H:%M} VN ({reason}) — equity {snap['equity']:,}"
            try:
                pushed = git_push(msg)
            except subprocess.CalledProcessError as exc:
                print(f"[push lỗi] {exc}")
            if pushed:
                store.set_meta("last_push_day", today)
                store.set_meta("last_push_ts", now.isoformat())

    print(f"{now:%Y-%m-%d %H:%M} VN | {status} | equity {snap['equity']:,} | "
          f"lệnh {snap['order_count']} | push: {reason or 'không'}"
          f"{' (đã đẩy)' if pushed else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
