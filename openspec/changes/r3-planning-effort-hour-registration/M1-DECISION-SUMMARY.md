# M1 — S12.5 Đăng ký công: GÓI QUYẾT ĐỊNH BÊN NGOÀI (bản cuối)

Đặc tả R3 V3 đã duyệt. Đã chốt: OD-01, OD-02, OD-04, OD-09, OD-42 (chủ dự án) và OD-03 (bằng chứng).
Còn **4** quyết định trước khi làm màn hình **Đăng ký công** (ma trận công đăng ký theo giai đoạn × bộ môn).
Chưa có câu trả lời = **không làm, không đoán**. Không đề xuất nào dưới đây là đã được phê duyệt.
Chi tiết bằng chứng: `M1-DECISION-PACK.md`.

## Thứ tự hỏi

1. **OD-25 — hỏi TRƯỚC.**
2. OD-07 · 3. OD-08 · 4. OD-05

**Nếu OD-25 = B (mục A.I thay thế Đăng ký công cũ):** OD-07 và OD-08 **không còn cần hỏi** cho M1 (chúng chỉ
áp dụng cho ma trận cũ); các mục đã chốt OD-01, OD-02, OD-03, OD-09, OD-42 cũng hết hiệu lực cho M1. M1 phải đặc tả
lại theo A.I và chờ các quyết định M2 (đơn vị, kỳ, nguồn bảng phân bổ, PM của dự án…). **OD-05 (quyền xem) vẫn
cần**, áp dụng cho màn hình thay thế.

---

## 1. OD-25 — Một chức năng hay hai?

| | |
|---|---|
| **Câu hỏi** | Màn hình "Đăng ký công" cũ (công đăng ký theo giai đoạn × bộ môn) và mục A.I của "Đăng ký công – rev01" (PM đăng ký công cho Quản lý phòng, PM, bộ môn) là **cùng một** chức năng hay **hai** chức năng? |
| **Legacy hiện nay** | Chọn dự án → ma trận giai đoạn của dự án × 5 bộ môn (Điện, Lạnh, Nước, BIM, QL); đơn vị "công"; ngân sách trọn đời; không duyệt, không khóa; người ghi: CEO, Thư ký, PM; báo cáo so "Công đăng ký" với "Công thực hiện". Rev01 A.I không nhắc giai đoạn. |
| **Đề xuất** | **A — hai chức năng tách riêng**: làm lại ma trận cũ trước (M1); A.I làm sau (M2), có thể lấy số từ ma trận cũ nếu M2 quyết định. |
| **Ảnh hưởng nghiệp vụ** | Người dùng có lại ngay màn hình quen thuộc và báo cáo so sánh cũ; dữ liệu 199 ô cũ được chuyển; A.I đến sau theo yêu cầu mới. |
| **Nếu chọn B (A.I thay thế)** | Không xây ma trận cũ; OD-07, OD-08 bỏ qua; M1 chờ các quyết định M2 → bản thử S12.5 khoảng 03–05/11 (mục tiêu do chủ dự án cung cấp) không giữ được; có thể mất ma trận theo giai đoạn. |
| **Ai duyệt** | **CUSTOMER** (CEO + PMO) |

## 2. OD-07 — Dự án ngưng/đóng

| | |
|---|---|
| **Câu hỏi** | Dự án đã ngưng hoặc đóng có còn hiện trong danh sách và **sửa** được công đăng ký không? |
| **Legacy hiện nay** | Hiện **mọi** dự án và cho sửa; màn hình cũ không có khái niệm dự án đóng. |
| **Đề xuất** | **A — như cũ**: hiện và sửa mọi dự án. |
| **Ảnh hưởng nghiệp vụ** | Không thay đổi thói quen; vẫn điều chỉnh được ngân sách cuối dự án. |
| **Nếu chọn B** | Dự án hoạt động: sửa được; dự án ngưng/đóng: **chỉ xem** → khóa ngân sách đã đóng, giảm sai sót, nhưng muốn điều chỉnh phải mở lại dự án. |
| **Ai duyệt** | **CUSTOMER** (PMO) |

## 3. OD-08 — Giai đoạn bị gỡ khỏi dự án

| | |
|---|---|
| **Câu hỏi** | Nếu một giai đoạn bị gỡ khỏi dự án sau khi đã đăng ký công, số đã đăng ký đó có **giữ lại và tính vào tổng** dự án không? |
| **Legacy hiện nay** | Dòng đó bị ẩn, vẫn được cộng trong báo cáo toàn dự án, rồi **bị xóa âm thầm** ở lần lưu sau (lỗi mất dữ liệu). Không xóa cứng là quy tắc dự án (D-7). |
| **Đề xuất** | **A — giữ**, hiện chỉ xem có nhãn "giai đoạn không còn trong dự án", **vẫn tính** vào tổng dự án. |
| **Ảnh hưởng nghiệp vụ** | Không mất dữ liệu; tổng giống báo cáo cũ; PM thấy rõ để tự điều chỉnh. |
| **Nếu chọn B** | Giữ dữ liệu nhưng ẩn và **không tính** vào tổng → tổng dự án giảm so với báo cáo cũ khi có giai đoạn bị gỡ. |
| **Ai duyệt** | **CUSTOMER** (PMO) |

## 4. OD-05 — Ai được xem Đăng ký công

| | |
|---|---|
| **Câu hỏi** | Những ai được **xem** ma trận Đăng ký công (người sửa đã chốt: Executive + PMO)? |
| **LEGACY** | **Manager / Leader / IT / HRD có quyền ĐỌC** (cùng người ghi CEO, Thư ký, PM). Member, AD: ẩn. |
| **TARGET CANDIDATES** | **Team Leader / Approver / Executive / PMO / HR / IT Support** (theo bảng ánh xạ vai trò cũ → mới — bảng này **chưa ký**; IT cũ → ứng viên IT Support). |
| **AppAdmin** | **DENY trong mọi phương án** (quyền kỹ thuật không phải quyền nghiệp vụ). |
| **Phương án A** | Cho xem: Team Leader, Approver, Executive, PMO, HR. **Không cho IT Support** — **siết bảo mật có chủ ý, lệch khỏi legacy** (IT cũ có quyền đọc). |
| **Phương án A2** | Như A nhưng **cho IT Support xem** để giữ đúng quyền đọc của IT cũ. |
| **Đề xuất** | **A** (quyền kỹ thuật không cần dữ liệu nghiệp vụ). Phân loại dữ liệu: **NỘI BỘ** (số công không chứa lương/chi phí). **Chưa phương án nào được phê duyệt.** |
| **Ảnh hưởng nghiệp vụ** | Nhóm người dùng nghiệp vụ giữ nguyên quyền xem; nhân viên IT mất quyền xem dữ liệu ngân sách công (A) hoặc giữ (A2). |
| **Nếu chọn A2** | IT Support được xem dữ liệu ngân sách công như legacy; bảo mật mục tiêu nới hơn đề xuất. |
| **Ai duyệt** | **BOTH** — SECURITY_OWNER (nhóm xem, phân loại) + CUSTOMER (xác nhận nhóm người dùng / việc bỏ quyền của IT cũ) |

---

Cổng M1: **BLOCKED** — còn 4: **OD-25, OD-07, OD-08, OD-05**. Đã chốt: OD-01, OD-02, OD-03, OD-04, OD-09, OD-42.
