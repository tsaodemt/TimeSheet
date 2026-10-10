# M2 — EPIC 16 Đăng ký công dự án (rev01 mục A.I và A.III): BIÊN BẢN QUYẾT ĐỊNH

Ngày 2026-10-10. **Đã chốt toàn bộ quyết định M2 — chưa triển khai.** M1 (màn hình Đăng ký công cũ, S12.5) đã XONG và giữ
nguyên. Cổng quyết định M2: **KHÔNG CÒN CÂU HỎI**. Bắt đầu làm M2 khi chủ dự án duyệt thiết kế dữ liệu / bảo mật, luồng,
giao diện, kiểm thử và điều kiện STAGING. Chi tiết: `M2-DECISION-PACK.md`.

## Bảng câu hỏi

Không còn câu hỏi nào cho M2.

## Quyết định đã chốt

| ID | Nội dung | Quyết định |
|---|---|---|
| OD-14 | Đơn vị công dự án | Ngày công (quy đổi từ giờ chấm công theo số giờ/ngày công đã duyệt); tối đa 2 số lẻ, nhập quá thì **từ chối**, không làm tròn — chỉ áp dụng cho EPIC 16 |
| OD-44 | Giới hạn giá trị | Nhỏ nhất 0; số âm bị từ chối; **không** giới hạn trên |
| OD-40 | Ô trống và 0 | Trống = chưa đăng ký; 0 = đăng ký bằng 0 |
| OD-16 | Nguồn số liệu A.I | PM **nhập tay**; không công thức, không nhập file |
| OD-22 | Giai đoạn | **Không** theo giai đoạn: dự án × đối tượng |
| OD-23 | Kỳ | **Cả đời dự án**; mọi thay đổi có nhật ký |
| OD-24 | PM của dự án | Mỗi dự án có **1 PM** (người cụ thể) do **PMO** cập nhật; chỉ PM đó được nhập công dự án; hệ thống kiểm tra ở máy chủ |
| OD-19 | Nguồn công thực hiện | Bảng chấm công hiện có; không thêm màn hình/danh sách; giữ nguyên quy tắc chấm công và nhập thay |
| OD-33 | Dòng chấm công được tính | **Chỉ dòng đã duyệt** (Approved); dòng nháp không tính |
| OD-37 | Quyền xem | PM của dự án (dự án của mình), PMO, Ban điều hành; vai trò khác **không** xem |
| OD-41 | Ai nhập thay công thực hiện | Không áp dụng (dùng quy tắc chấm công hiện có) |

Ghi chú: OD-24 được ghi theo đúng nội dung chủ dự án viết ("mỗi project có 1 PM, PMO quản lý"), tức phương án (b) trong
danh sách cũ — không phải "mọi PMO sửa mọi dự án".

## Giữ nguyên, không mở lại

- **OD-26:** mục A.I **không có** phê duyệt / bỏ duyệt / khóa / mở khóa.
- **OD-25:** Đăng ký công cũ (M1) và công dự án A.I là hai chức năng riêng; không dùng chung dữ liệu hay trường, không liên
  kết số liệu, không lấy số cũ làm số ban đầu.

## Chuyển sang M3 (không chặn M2)

Đơn vị công bộ môn (OD-45) và quyền xem dữ liệu bộ môn của Trưởng bộ môn / Quản lý phòng (OD-46; báo cáo Quản lý phòng:
OD-31) sẽ hỏi ở M3/M4.
