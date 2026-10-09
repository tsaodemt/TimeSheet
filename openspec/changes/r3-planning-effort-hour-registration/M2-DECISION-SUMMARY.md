# M2 — EPIC 16 Đăng ký công dự án (rev01 mục A.I và A.III): TÓM TẮT QUYẾT ĐỊNH

Ngày 2026-10-10. **Chỉ chốt quyết định — chưa triển khai.** M1 (màn hình Đăng ký công cũ, S12.5) đã XONG và giữ nguyên.
Cổng M2: **BLOCKED — CHỜ CHỦ DỰ ÁN / KHÁCH HÀNG QUYẾT ĐỊNH.** Chưa có câu trả lời = **không làm, không đoán**.
Mọi "khuyến nghị" dưới đây **chưa được phê duyệt**. Chi tiết bằng chứng: `M2-DECISION-PACK.md`.

Đã rõ từ tài liệu rev01, **không cần hỏi lại**: người đăng ký mục A.I là PM; đối tượng nhận công = Quản lý phòng, PM,
bộ môn điện, lạnh, nước, BIM; mục A.I **không có** phê duyệt/khóa (OD-26); "mục I.3" = A.I.3; Đăng ký công cũ (M1) là
chức năng riêng, không gộp với A.I (OD-25).

## Bảng quyết định

| ID | Câu hỏi | Khuyến nghị | Ai quyết định | Chặn M2 |
|---|---|---|---|---|
| OD-24 | "PM của dự án" là ai, lưu ở đâu? (dữ liệu dự án hiện **không có** trường PM) | Mỗi dự án có 1 PM (người cụ thể) do PMO cập nhật; hệ thống kiểm tra phạm vi dự án ở máy chủ | Khách hàng (CEO + PMO) + phụ trách bảo mật | Có |
| OD-19 | "Công thực hiện" (A.III) lấy từ bảng chấm công hiện có hay nhập riêng? | Lấy từ **chấm công hiện có** (không nhập 2 lần) | Khách hàng (CEO + PMO) | Có |
| OD-14 | Đơn vị "công" là gì? | **Ngày công** = 8 giờ (`HoursPerManDay`), tối đa 2 số lẻ — chỉ cần xác nhận | Khách hàng (CEO + PMO) — xác nhận | Có |
| OD-22 | Công dự án (A.I) đăng ký theo **dự án** hay theo **từng giai đoạn**? | Theo dự án × đối tượng, **không** theo giai đoạn | Khách hàng (PMO + Kế toán) | Có |
| OD-23 | Công dự án tính **cả đời dự án**, theo năm, tháng hay kỳ lương? | **Cả đời dự án**; thay đổi được lưu vết | Khách hàng (PMO) | Có |
| OD-16 | Số liệu "bảng phân bổ sản lượng dự án" vào hệ thống thế nào? | PM **nhập tay**, có ô ghi tham chiếu bảng; chưa nhập file, không công thức | Khách hàng (PMO + Kế toán) | Có |
| OD-40 | Ô **trống** khác **0**? | Trống = chưa đăng ký; 0 = đăng ký bằng 0 | Khách hàng (PMO) | Có |
| OD-37 | Ai được **xem** công dự án? | PM của dự án, PMO, Ban điều hành; Trưởng bộ môn xem dòng bộ môn mình (quyết ở M3); Quản lý phòng (quyết ở M4); còn lại **không** | Khách hàng (CEO + PMO) + phụ trách bảo mật | Có |
| OD-41 | Nếu công thực hiện nhập riêng: ai được nhập thay ai? | Không cần hỏi nếu OD-19 = lấy từ chấm công | CEO + PMO | Chỉ khi OD-19 = nhập riêng/kết hợp |

Thứ tự hỏi đề xuất: **OD-24 → OD-19 → OD-14 → OD-22 → OD-23 → OD-16 → OD-40 → OD-37**.

## Thẻ quyết định (ngắn)

**OD-24 — PM của dự án.** rev01 ghi "Người thực hiện: PM". Hiện dữ liệu dự án (cũ và mới) không có người PM của từng dự án;
bảng phân công nhân sự–dự án cũ không có vai trò và không dùng. Không thể đảm bảo "chỉ PM của dự án được đăng ký" nếu
không có dữ liệu này. Phương án: a) mọi người vai trò PMO đều sửa mọi dự án; b) mỗi dự án ghi 1 PM do PMO quản lý (khuyến
nghị); c) b + PMO được sửa thay. Ảnh hưởng: thêm thông tin PM cho dự án, kiểm tra phạm vi dự án ở máy chủ.

**OD-19 — Nguồn công thực hiện.** rev01 A.III ghi "Chấm công thực hiện dự án" — "Chấm công" là tên phân hệ bảng chấm công;
hệ thống cũ tính "Công thực hiện" từ giờ chấm công ÷ 8. Phương án: a) lấy từ chấm công (khuyến nghị); b) nhập riêng;
c) kết hợp. Nếu a: giữ nguyên quy tắc chấm công hiện tại (kể cả nhập thay đã được phép), OD-41 không áp dụng. Nếu b/c:
phải chốt thêm OD-41.

**OD-14 — Đơn vị.** rev01 chỉ dùng chữ "công"; trong hệ thống cũ "Công đăng ký" và "Công thực hiện" đều là ngày công
(8 giờ). Khuyến nghị xác nhận: 1 công = 1 ngày công = 8 giờ, tối đa 2 số lẻ.

**OD-22 — Giai đoạn.** Mục A.I không nhắc giai đoạn; giai đoạn chỉ xuất hiện ở phần thống kê chi phí (B.II). Khuyến nghị:
công dự án theo dự án × đối tượng; chi phí theo giai đoạn lấy từ công thực hiện.

**OD-23 — Kỳ.** rev01 không nêu kỳ. A.I là "đăng ký công cho dự án" và là mức trần cho bộ môn. Khuyến nghị: tổng cả đời dự
án; mọi thay đổi có nhật ký.

**OD-16 — Nguồn số liệu A.I.** rev01 ghi "từ bảng phân bổ sản lượng dự án" nhưng không mô tả bảng. Khuyến nghị: PM nhập
tay (kèm ghi chú tham chiếu); nhập file Excel để sau khi biết định dạng (OD-36).

**OD-40 — Trống và 0.** rev01 không nói. Khuyến nghị: trống = chưa đăng ký, 0 = đăng ký bằng 0 (quyết định riêng cho A.I,
không chép từ màn hình Đăng ký công cũ).

**OD-37 — Quyền xem.** Không dùng lại quyền xem của màn hình Đăng ký công cũ. Khuyến nghị: PM của dự án (theo OD-24), PMO,
Ban điều hành; các vai trò khác không xem; Trưởng bộ môn và Quản lý phòng quyết ở M3/M4.

## Giữ nguyên, không mở lại

- **OD-26:** mục A.I **không có** phê duyệt/khóa (rev01 chỉ nêu phê duyệt ở A.II và A.III).
- **OD-25:** Đăng ký công cũ (M1) và công dự án A.I là hai chức năng riêng; không dùng chung dữ liệu, không lấy số cũ làm số
  ban đầu.

Ghi chú: OD-43 (bộ môn "Quản lý" trong danh mục có phải là "Quản lý phòng" không) **không chặn M2**; mặc định theo đúng chữ
rev01: Quản lý phòng, PM, điện, lạnh, nước, BIM.
