# M2 — EPIC 16 Đăng ký công dự án (rev01 mục A.I và A.III): CÂU HỎI CÒN LẠI

Ngày 2026-10-10. **Chỉ chốt quyết định — chưa triển khai.** M1 (màn hình Đăng ký công cũ, S12.5) đã XONG và giữ nguyên.
Cổng M2: **BLOCKED — CHỜ KHÁCH HÀNG / PHỤ TRÁCH BẢO MẬT QUYẾT ĐỊNH 5 câu hỏi dưới đây.** Chưa có câu trả lời = **không làm,
không đoán**. Mọi "khuyến nghị" **chưa được phê duyệt**. Chi tiết bằng chứng: `M2-DECISION-PACK.md`.

Chủ dự án đã chốt, **không hỏi lại**: đơn vị công dự án = **ngày công** (quy đổi từ giờ chấm công theo số giờ/ngày công
đã duyệt, tối đa 2 số lẻ); **công thực hiện lấy từ bảng chấm công hiện có** (không thêm màn hình/danh sách nhập riêng, giữ
nguyên quy tắc chấm công và nhập thay hiện tại); **ô trống = chưa đăng ký, 0 = đăng ký bằng 0**. Đã rõ từ rev01: người đăng
ký A.I là PM; đối tượng nhận công = Quản lý phòng, PM, bộ môn điện, lạnh, nước, BIM; mục A.I **không có** phê duyệt/khóa;
Đăng ký công cũ (M1) là chức năng riêng, không gộp, không lấy số cũ làm số ban đầu.

## Bảng câu hỏi

| ID | Câu hỏi | Khuyến nghị | Người quyết định | Chặn M2 |
|---|---|---|---|---|
| OD-24 | "PM của dự án" là ai, lưu ở đâu? (dữ liệu dự án hiện **không có** trường PM) | Mỗi dự án có **1 PM** (người cụ thể) do PMO cập nhật; hệ thống kiểm tra ở máy chủ | Khách hàng (CEO + PMO) **và** phụ trách bảo mật | Có |
| OD-22 | Công dự án (A.I) đăng ký theo **dự án** hay theo **từng giai đoạn**? | Theo dự án × đối tượng, **không** theo giai đoạn | Khách hàng (PMO + Kế toán) | Có |
| OD-23 | Công dự án tính **cả đời dự án**, theo năm, tháng hay kỳ lương? | **Cả đời dự án**; mọi thay đổi được lưu vết | Khách hàng (PMO) | Có |
| OD-16 | Số liệu "bảng phân bổ sản lượng dự án" vào hệ thống thế nào? | PM **nhập tay** công dự án; không công thức, không nhập file (trừ khi yêu cầu riêng) | Khách hàng (PMO + Kế toán) | Có |
| OD-37 | Ai được **xem** công dự án? | PM của dự án, PMO, Ban điều hành; **không** dùng lại quyền xem của màn hình Đăng ký công cũ | Khách hàng (CEO + PMO) **và** phụ trách bảo mật | Có |

Thứ tự hỏi đề xuất: **OD-24 → OD-22 → OD-23 → OD-16 → OD-37**.

## Thẻ câu hỏi

**OD-24 — PM của dự án.** rev01 ghi "Người thực hiện: PM". Dữ liệu dự án (cũ và mới) không có người PM của từng dự án;
bảng phân công nhân sự–dự án cũ không có vai trò và không dùng. Không thể đảm bảo "chỉ PM của dự án được đăng ký" nếu
không có dữ liệu này. Phương án: a) mọi người vai trò PMO đều sửa mọi dự án; b) mỗi dự án ghi 1 PM do PMO quản lý, kiểm tra
ở máy chủ (khuyến nghị); c) b + PMO được sửa thay. Ảnh hưởng: thêm thông tin PM cho dự án, kiểm tra phạm vi dự án ở máy
chủ. Cần cả khách hàng (nghiệp vụ) và phụ trách bảo mật (mô hình phạm vi) xác nhận.

**OD-22 — Giai đoạn.** Mục A.I không nhắc giai đoạn; giai đoạn chỉ xuất hiện ở phần thống kê chi phí (B.II). Khuyến nghị:
công dự án theo dự án × đối tượng, không có chiều giai đoạn; chi phí theo giai đoạn lấy từ công thực hiện (chấm công vẫn có
giai đoạn). **Chưa được duyệt.**

**OD-23 — Kỳ.** rev01 không nêu kỳ. A.I là "đăng ký công cho dự án" và là mức trần cho bộ môn. Khuyến nghị: một giá trị
cho cả đời dự án; mọi thay đổi có nhật ký/lịch sử. **Chưa được duyệt.**

**OD-16 — Nguồn số liệu A.I.** rev01 ghi "từ bảng phân bổ sản lượng dự án" nhưng không mô tả bảng. Khuyến nghị: PM nhập tay
công dự án (có thể ghi chú tham chiếu bảng); không thêm công thức hay nhập file Excel nếu không có yêu cầu riêng.

**OD-37 — Quyền xem.** Khuyến nghị: XEM = PM của dự án (theo OD-24), PMO, Ban điều hành; các vai trò khác không xem. Không
dùng lại quyền xem của màn hình Đăng ký công cũ. Quyền xem của Trưởng bộ môn / Quản lý phòng thuộc các quyết định sau (khi
áp dụng). Cần cả khách hàng và phụ trách bảo mật xác nhận. **Chưa được duyệt.**

## Giữ nguyên, không mở lại

- **OD-26:** mục A.I **không có** phê duyệt / bỏ duyệt / khóa / mở khóa.
- **OD-25:** Đăng ký công cũ (M1) và công dự án A.I là hai chức năng riêng; không dùng chung dữ liệu hay trường, không liên
  kết số liệu, không lấy số cũ làm số ban đầu — kể cả khi cả hai cùng đơn vị ngày công.

Ghi chú: OD-43 (bộ môn "Quản lý" trong danh mục có phải là "Quản lý phòng" không) **không chặn M2**; mặc định theo đúng chữ
rev01: Quản lý phòng, PM, điện, lạnh, nước, BIM.
