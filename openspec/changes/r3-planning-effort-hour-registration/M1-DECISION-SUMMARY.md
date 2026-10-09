# M1 — S12.5 Đăng ký công: tóm tắt quyết định (dùng cho buổi họp)

Đặc tả R3 V3 đã duyệt. Chủ dự án đã chốt OD-01, OD-02, OD-04, OD-09 (= A); OD-03 chốt bằng bằng chứng
(số, tối đa 2 chữ số thập phân). Còn **5** quyết định trước khi làm màn hình **Đăng ký công**. Chi tiết:
`M1-DECISION-PACK.md`. Chưa có câu trả lời = **không làm, không đoán**.

## Câu hỏi cho khách hàng (theo thứ tự)

| # | ID | Câu hỏi | Đề xuất | Chặn |
|---|---|---|---|---|
| 1 | OD-25 | Màn hình "Đăng ký công" cũ và mục A.I của "Đăng ký công – rev01" (PM đăng ký công cho QLP, PM, bộ môn) là một hay hai chức năng? | **A – tách riêng**: làm lại ma trận cũ trước (M1), A.I sau (M2) | M1, M2 |
| 2 | OD-07 | Dự án ngưng/đóng có hiện và sửa ngân sách được không? | **A – như cũ: hiện và sửa mọi dự án** (B: chỉ xem nếu muốn khóa) | M1 |
| 3 | OD-08 | Số trên giai đoạn bị gỡ khỏi dự án: giữ và tính vào tổng không? | **A – giữ, hiện chỉ xem có nhãn, vẫn tính vào tổng** | M1 |

Nếu câu 1 = B (A.I thay thế màn hình cũ): câu 2–3 và giới hạn giá trị không còn áp dụng cho M1; M1 chờ quyết định M2.

## Chủ dự án / chủ bảo mật chốt (OD-05 có thể cần khách hàng nếu bị tranh luận)

| ID | Câu hỏi | Đề xuất | Chặn |
|---|---|---|---|
| OD-05 | Ai được xem; mức phân loại? Legacy: đọc = Manager, Leader, **IT**, HRD. Bảng ánh xạ vai trò chưa ký; IT cũ → ứng viên **IT Support** | **Cho xem: TL, Approver, Executive, PMO, HR; không AppAdmin, không IT Support (lệch có chủ ý so với legacy — IT cũ có quyền đọc — cần duyệt); NỘI BỘ** | M1 |
| OD-42 | Giới hạn giá trị tối thiểu/tối đa? | **Tối thiểu 0, không đặt tối đa nghiệp vụ** | M1 |

## Đã chốt

| ID | Kết quả |
|---|---|
| OD-01 | Trống ≠ 0 (tổng báo cáo không đổi) |
| OD-02 | Dòng = giai đoạn của dự án |
| OD-03 | Chỉ nhận số; số lẻ tối đa 2 chữ số thập phân |
| OD-04 | Sửa/lưu: Executive + PMO; không AppAdmin |
| OD-09 | Xóa ô = giữ bản ghi, giá trị rỗng |

Cổng M1: **BLOCKED** — còn 5 (OD-25, OD-07, OD-08, OD-05, OD-42). Lịch mục tiêu do chủ dự án cung cấp
(bản thử S12.5 trên STAGING khoảng 03–05/11) cần các câu trả lời này sớm.
