# 📈 Khanh Stock Board — Paper Trading

Bảng theo dõi **mô phỏng giao dịch (paper)** chiến lược MA cross trên cổ phiếu VN.
Tự động chạy 1 tick mỗi phiên (sau khi HOSE đóng cửa) qua GitHub Actions, cập nhật
biểu đồ đường tài sản + lịch sử lệnh, hiển thị qua GitHub Pages.

> ⚠️ **Vốn ẢO, mô phỏng học tập — KHÔNG phải lời khuyên đầu tư.** Không đặt lệnh
> thật, không dùng API broker, **không chứa secret nào**. Chỉ đọc dữ liệu giá
> công khai qua [vnstock](https://github.com/thinh-vu/vnstock).

## Xem board

Sau khi bật GitHub Pages (xem dưới): **https://khanhnguyen3759.github.io/khanh-stock-board/**

## Cách hoạt động

```
vnstock (giá VND) → MA cross → risk gate (trần vốn) → paper executor → SQLite
                                                                          ↓
                                            docs/data.json → trang Pages (Chart.js)
```

- `engine/` — engine paper tự chứa: feed giá, strategy MA cross, risk gate, paper
  executor, state SQLite (idempotent qua `client_id` → chạy lại không nhân đôi lệnh).
- `scripts/run.py` — chạy 1 tick, cập nhật state, xuất `docs/data.json`.
- `scripts/seed.py` — seed lịch sử ban đầu (backtest) để board có dữ liệu ngay.
- `docs/` — trang tĩnh hiển thị (HTML + Chart.js), đọc `data.json`. GitHub Pages
  phục vụ từ thư mục này.
- `data/paper.db` — state mô phỏng (commit lại mỗi lần CI để bền vững).

## Cấu hình (biến môi trường, đều có mặc định)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `WATCHLIST` | `ACB,FPT,MWG` | Mã theo dõi |
| `PAPER_CAPITAL` | `200000000` | Vốn ảo khởi đầu (VND) |
| `MIN_ORDER_VALUE` | `1000000` | Dưới mức này → kill switch |
| `MA_FAST` / `MA_SLOW` | `10` / `20` | Tham số MA cross |

## Chạy thủ công

```bash
pip install -r requirements.txt
python -m scripts.seed 365     # 1 lần, tạo lịch sử ban đầu (DB sạch)
python -m scripts.run          # 1 tick, cập nhật docs/data.json
```

## Bật GitHub Pages (làm 1 lần)

Settings → Pages → **Source: Deploy from a branch** → Branch `main`, thư mục `/docs`
→ Save. (GitHub Pages chỉ cho chọn `/(root)` hoặc `/docs` — nên dùng `/docs`.)
Vài phút sau truy cập link board ở trên.

GitHub Actions tự chạy tick **~18:00 giờ VN (T2–T6)** — sau khi dữ liệu EOD đã chốt
(GitHub cron là best-effort nên giờ thực tế có thể trễ; engine chỉ giao dịch khi nến
mới nhất = hôm nay nên trễ vẫn an toàn). Có thể bấm chạy tay ở tab Actions.

> **Chiến lược chỉ giao dịch khi có giao cắt MA** (vài lần/tháng mỗi mã), không mua
> bán mỗi ngày. Theo dõi lời/lỗ liên tục qua **đường Equity**, không phải số dòng lệnh.
