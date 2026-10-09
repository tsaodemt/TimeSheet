# M1 — S12.5 Đăng ký công: tóm tắt quyết định (dùng cho buổi họp)

Đặc tả R3 V3 đã được duyệt. Để bắt đầu làm màn hình **Đăng ký công** (ma trận công đăng ký theo giai đoạn × bộ môn),
cần chốt các điểm dưới đây. Chi tiết và bằng chứng: `M1-DECISION-PACK.md`. Chưa có câu trả lời = **không làm, không đoán**.

| ID | Câu hỏi | Đề xuất | Khách hàng phải trả lời? | Chặn |
|---|---|---|---|---|
| OD-25 | Màn hình "Đăng ký công" cũ và mục A.I của "Đăng ký công – rev01" (PM đăng ký công cho QLP, PM, bộ môn) là một hay hai chức năng? | **A – tách riêng**: làm lại ma trận cũ trước (M1), A.I làm sau (M2) | **CÓ** (CEO + PMO) — hỏi đầu tiên | M1, M2 |
| OD-07 | Dự án đã ngưng/đóng có hiện và sửa ngân sách được không? | **A – như cũ: hiện và sửa mọi dự án** (hoặc B: chỉ xem nếu muốn khóa) | **CÓ** (PMO) | M1 |
| OD-08 | Số đã đăng ký trên giai đoạn bị gỡ khỏi dự án: giữ và tính vào tổng không? | **A – giữ, hiện chỉ xem có đánh dấu, vẫn tính vào tổng dự án** | **CÓ** (PMO) | M1 |
| OD-01 | "0" và ô trống có khác nhau? | **A – khác nhau** (tổng báo cáo không đổi) | Không — chủ dự án quyết, báo khách hàng | M1 |
| OD-03 | Giá trị hợp lệ của ô? | **≥ 0, tối đa 2 số lẻ, ≤ 9.999** | Không — chủ dự án quyết | M1 |
| OD-05 | Ai được xem; mức phân loại? | **TL, Approver, Executive, PMO, HR; không cho AppAdmin/IT; NỘI BỘ** | Không — chủ dự án (± HR) | M1 |
| OD-02 | Dòng ma trận = giai đoạn của dự án hay tất cả? | **Giai đoạn của dự án (như cũ)** | Không — đã rõ từ phần mềm cũ | đóng bằng bằng chứng |
| OD-04 | Ai được sửa/lưu? | **Executive + PMO** (không AppAdmin) | Không — ánh xạ quyền cũ + yêu cầu chủ dự án | đóng bằng bằng chứng |
| OD-09 | Xóa ô thì lưu gì? | **Giữ bản ghi, giá trị rỗng** (không xóa cứng, theo D-7) | Không — kỹ thuật | đóng bằng bằng chứng |

**Cần khách hàng: 3 câu (OD-25 trước, rồi OD-07, OD-08).** Chủ dự án tự chốt: 3 (OD-01, OD-03, OD-05). Đóng bằng bằng
chứng chờ chủ dự án xác nhận: 3 (OD-02, OD-04, OD-09).

Nếu OD-25 = B (A.I thay thế màn hình cũ): OD-01, 02, 03, 07, 08, 09 không còn áp dụng cho M1 và M1 phải chờ các
quyết định của M2.

Cổng M1: **BLOCKED** — còn 6 quyết định (OD-01, OD-03, OD-05, OD-07, OD-08, OD-25). Lịch mục tiêu do chủ dự án cung cấp
(bản thử S12.5 trên STAGING khoảng 03–05/11) chỉ giữ được nếu các quyết định này được chốt sớm.
