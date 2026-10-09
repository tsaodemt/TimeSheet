# Gói quyết định M1 — S12.5 Đăng ký công (Hour Registration)

Trạng thái (2026-10-09): **CHUẨN BỊ QUYẾT ĐỊNH — CHƯA TRIỂN KHAI.** Open Spec V3 đã duyệt (R3-G0 = APPROVED).
READY_FOR_IMPLEMENTATION = NO. Cổng M1 **BLOCKED** cho tới khi 4 quyết định còn mở có câu trả lời ghi nhận.
Chưa có câu trả lời: **BLOCK / KHÔNG ĐOÁN**. Đề xuất bên dưới chưa được phê duyệt.

Nhãn bằng chứng: **LEGACY_FACT** · **TARGET_SECURITY_REQUIREMENT** · **OWNER_PROVIDED_REQUIREMENT** ·
**PROPOSED_MODERNIZATION** · **OPEN_BUSINESS_DECISION**.

## 0. Tình trạng 10 quyết định M1 (9 ban đầu + OD-42 tách từ OD-03)

| ID | Nội dung | Tình trạng | Ai |
|---|---|---|---|
| OD-01 | Trống ≠ 0 | **ĐÃ CHỐT = A** (chủ dự án, 2026-10-09) | – |
| OD-02 | Dòng = giai đoạn của dự án | **ĐÃ CHỐT = A** (bằng chứng, chủ dự án chấp thuận) | – |
| OD-03 | Kiểu giá trị & độ chính xác | **ĐÃ CHỐT BẰNG BẰNG CHỨNG**: số, cho phép số lẻ, tối đa 2 chữ số thập phân; giới hạn min/max tách sang OD-42 | – |
| OD-04 | Ai được sửa/lưu | **ĐÃ CHỐT = A**: Executive + PMO; AppAdmin không | – |
| OD-09 | Xóa ô lưu gì | **ĐÃ CHỐT = A**: giữ bản ghi, giá trị rỗng | – |
| OD-25 | Màn hình cũ vs rev01 A.I | **MỞ** — hỏi **đầu tiên** | Khách hàng (CEO + PMO) |
| OD-07 | Dự án ngưng/đóng | **MỞ** | Khách hàng (PMO) |
| OD-08 | Số trên giai đoạn bị gỡ | **MỞ** | Khách hàng (PMO) |
| OD-05 | Ai được xem; phân loại | **MỞ** — CUSTOMER_OR_SECURITY_OWNER_REQUIRED | Chủ bảo mật + khách hàng (BOTH) |
| OD-42 | Giới hạn min/max của giá trị (tách từ OD-03) | **ĐÃ CHỐT** (chủ dự án, 2026-10-09): tối thiểu 0, cấm số âm, không có tối đa nghiệp vụ | – |

**Còn chặn M1: 4** — OD-25, OD-07, OD-08, OD-05. Bản hỏi bên ngoài cuối cùng: `M1-DECISION-SUMMARY.md`.

## 1. Thứ tự & phụ thuộc

```text
OD-25 ← hỏi TRƯỚC
  ├─ (a) tách riêng / (c) mở rộng → các quyết định S12.5 (đã chốt và còn mở) áp dụng cho M1
  └─ (b) A.I thay thế S12.5 → OD-07, OD-08 và các mục đã chốt OD-01/02/03/09/42 không còn áp dụng cho M1
       (M1 phải đặc tả lại theo A.I và chờ quyết định M2); OD-04/OD-05 (quyền) vẫn cần cho màn hình thay thế
OD-08 chỉ có nghĩa vì dòng = giai đoạn của dự án (OD-02 = A)
OD-05, OD-07: độc lập với nhau
```

---

## A. Quyết định đã chốt (ghi lại để truy vết)

| ID | Kết quả | Bằng chứng |
|---|---|---|
| OD-01 | A — ô trống (chưa đăng ký) khác "0" (đã đăng ký 0) ở lưu trữ, giao diện, khứ hồi; báo cáo cộng trống như 0 | OWNER decision 2026-10-09. LEGACY_FACT: tệp cũ phân biệt "" và "0" (4 ô "0"), giao diện cũ gộp chúng; tổng báo cáo không đổi |
| OD-02 | A — dòng = giai đoạn của dự án, theo thứ tự của dự án | LEGACY_FACT đã kiểm chứng; không có yêu cầu khách hàng thay đổi; chủ dự án chấp thuận |
| OD-03 | Chỉ nhận số; cho phép số lẻ; **tối đa 2 chữ số thập phân**; nhập dấu phẩy được chuẩn hóa | LEGACY_FACT: phần mềm cũ đọc số lẻ (dấu chấm), **không giới hạn độ chính xác khi nhập**, mọi đầu ra (tổng báo cáo) hiển thị **2 chữ số thập phân**; dữ liệu thực tế chỉ có số nguyên. Giữ 2 chữ số không làm mất gì người dùng từng thấy. Chữ/ký tự rác bị mất âm thầm ở legacy → sửa lỗi (từ chối có thông báo). **Không** chốt giới hạn trên/dưới (→ OD-42) |
| OD-04 | A — `REG.Edit` = Executive + PMO; AppAdmin bị từ chối | LEGACY_FACT: quyền ghi CEO, Thư ký, PM (+ Admin bỏ qua kỹ thuật); OWNER_PROVIDED_REQUIREMENT: quản trị kỹ thuật không có quyền nghiệp vụ; chủ dự án chấp thuận |
| OD-42 | Tối thiểu 0; số âm bị từ chối; **không có tối đa nghiệp vụ**; tối đa 2 chữ số thập phân (OD-03); kiểm tra số ở máy chủ (và máy người dùng). Giới hạn nền tảng (số thực ~15 chữ số có nghĩa của SharePoint/Power Fx) là TECHNICAL_LIMIT, không phải quy tắc nghiệp vụ | OWNER decision 2026-10-09 |
| OD-09 | A — xóa ô = giữ bản ghi, giá trị rỗng (null) | Quyết định dự án D-7 (không xóa cứng, dịch vụ không có quyền Delete); chủ dự án chấp thuận |

---

## B. Quyết định còn mở

### OD-25 — "Đăng ký công" cũ và mục A.I của "Đăng ký công – rev01" là một hay hai chức năng? (HỎI TRƯỚC)

| Mục | Nội dung |
|---|---|
| Câu hỏi | Ma trận "Công đăng ký cho dự án" của phần mềm cũ (dự án × giai đoạn × bộ môn) và việc PM đăng ký công dự án cho Quản lý phòng, PM, các bộ môn (rev01 A.I) là cùng một chức năng hay hai chức năng khác nhau? |
| Vì sao cần | Quyết định có xây S12.5 theo dạng cũ hay không; tránh làm hai lần hoặc chuyển 199 ô cũ vào sai chỗ. |
| Legacy (LEGACY_FACT) | Chọn dự án → ma trận giai đoạn của dự án × 5 bộ môn (Điện, Lạnh, Nước, BIM, QL), đơn vị "công", ngân sách trọn đời; không duyệt, không khóa; người ghi CEO, Thư ký, PM; báo cáo so "Công đăng ký" với "Công thực hiện". |
| Rev01 (OPEN_BUSINESS_DECISION) | "Người thực hiện: PM; Dữ liệu: từ bảng phân bổ sản lượng dự án; Công đăng ký: cho Quản lý phòng, PM, bộ môn (điện, lạnh, nước, BIM)". Không nhắc giai đoạn; được phân loại là yêu cầu mới. |
| A | **Tách riêng**: S12.5 = ma trận cũ (M1); A.I là chức năng mới ở M2 (có thể lấy số từ S12.5 nếu M2 quyết). |
| B | **A.I thay thế S12.5**: không xây ma trận cũ; M1 chờ quyết định M2 (đơn vị, kỳ, nguồn bảng phân bổ, PM của dự án…). |
| C | **Mở rộng chung**: một thực thể; ma trận cũ thêm cột QLP/PM và quy tắc rev01. |
| Đề xuất | **A** — không có yêu cầu nói A.I thay thế màn hình cũ; ngữ nghĩa cũ đã kiểm chứng và đang dùng cho báo cáo; giữ được tiến độ S12.5. |
| Ảnh hưởng | A: màn hình quen thuộc có ngay, A.I đến sau. B: mất ma trận theo giai đoạn nếu rev01 không có giai đoạn; trễ M1. |
| Dữ liệu | A: chuyển 199 ô sang `HourRegistrations`. B: chuyển vào thực thể A.I hoặc không chuyển (cần quy tắc). |
| Nếu từ chối A | Lịch mục tiêu do chủ dự án cung cấp (bản thử S12.5 khoảng 03–05/11) không giữ được. |
| Ai quyết | **Khách hàng** (CEO + PMO). Mặc định: **BLOCK / KHÔNG ĐOÁN**. |

### OD-07 — Dự án ngưng/đóng có được hiển thị và sửa ngân sách không?

| Mục | Nội dung |
|---|---|
| Legacy (LEGACY_FACT) | Liệt kê **mọi** dự án (cờ lọc là trạng thái giao diện, luôn bật) và cho sửa; màn hình cũ không có khái niệm dự án đóng. |
| Mục tiêu | Danh mục dự án mới có trạng thái; chưa quyết cho Đăng ký công. |
| A | Như cũ: liệt kê và sửa mọi dự án. |
| B | Dự án hoạt động: sửa; dự án khác: chỉ xem. |
| C | Chỉ liệt kê dự án hoạt động. |
| Đề xuất | **A** (ngữ nghĩa legacy); B nếu khách hàng muốn khóa ngân sách dự án đã đóng. |
| Ai quyết | **Khách hàng** (PMO). Mặc định: **BLOCK / KHÔNG ĐOÁN**. |

### OD-08 — Số đã đăng ký trên giai đoạn bị gỡ khỏi dự án / bộ môn ngưng dùng

| Mục | Nội dung |
|---|---|
| Legacy (LEGACY_FACT) | Dòng của giai đoạn đã gỡ bị ẩn, vẫn được cộng trong báo cáo toàn dự án tới lần lưu sau, rồi **bị xóa âm thầm**. Bộ môn: legacy hiện mọi bộ môn trong danh mục. Dữ liệu: 1 dòng như vậy, toàn ô trống. |
| Ràng buộc | D-7: không xóa cứng → loại phương án "xóa". |
| A | Giữ, hiện chỉ xem có nhãn "giai đoạn không còn trong dự án", **vẫn tính** vào tổng dự án. |
| B | Giữ nhưng ẩn và **không tính** vào tổng. |
| Đề xuất | **A** — không mất dữ liệu; tổng giống báo cáo legacy; người dùng thấy rõ để xử lý. |
| Ai quyết | **Khách hàng** (PMO). Mặc định: **BLOCK / KHÔNG ĐOÁN**. |

### OD-05 — Ai được xem ma trận; mức phân loại dữ liệu

| Mục | Nội dung |
|---|---|
| Legacy (LEGACY_FACT) | Dữ liệu quyền module "TS.Đăng ký công": **Ghi** = CEO, Thư ký, PM; **Đọc** = Manager, Leader, **IT**, HRD; **Ẩn** = Member, AD; Director không có dòng (vai trò đã bỏ); Admin bỏ qua kiểm tra. **IT cũ CÓ quyền đọc Đăng ký công.** Tệp được coi là nội bộ. |
| Bằng chứng mục tiêu | Bảng ánh xạ vai trò cũ → mới: Manager → Approver; Leader → Team Leader; HRD → HR; CEO → Executive hoặc Approver; Thư ký/PM → PMO; **IT → tách** (IT Support = phần kỹ thuật; App Administrator = sửa phân quyền; HR = khóa người dùng; Salary Viewer = xem lương). Vai trò mục tiêu ứng viên cho quyền **đọc** Đăng ký công của IT cũ là **IT Support**. Bảng ánh xạ ở trạng thái **"PREPARED LOCALLY / chờ ký"**, chưa phê duyệt; seed `REG.View` hiện tại (gồm AppAdmin) chưa phê duyệt; phân loại dữ liệu mâu thuẫn (legacy: nội bộ; một ghi chú mục tiêu: "Mật (ngân sách)"). → **Không có quy tắc vai trò/bảo mật đã phê duyệt** xác lập nhóm xem. |
| Yêu cầu chủ dự án | AppAdmin và IT Support **không** được quyền xem nghiệp vụ chỉ vì quyền kỹ thuật (OWNER_PROVIDED_REQUIREMENT). |
| A | **Cho xem**: Team Leader, Approver, Executive, PMO, HR (ánh xạ của người đọc Manager/Leader/HRD và người ghi CEO/Thư ký/PM). **Không cho xem**: AppAdmin, IT Support. Phân loại NỘI BỘ trên site vận hành. **Lưu ý:** từ chối IT Support là **SIẾT BẢO MẬT MỤC TIÊU / LỆCH KHỎI LEGACY** — IT cũ **có** quyền đọc; cần chủ bảo mật / khách hàng phê duyệt trong OD-05; **không phải** RESOLVED_BY_EVIDENCE. |
| A2 | Như A nhưng **giữ quyền đọc cho IT Support** (giữ đúng legacy: IT cũ có quyền đọc). AppAdmin vẫn không. |
| B | Như A nhưng phân loại MẬT → đặt ở vùng dữ liệu mật (phụ thuộc ENV-D2 chưa có quyết định → trễ M1). |
| Đề xuất | **A** — giữ nhóm người dùng nghiệp vụ của legacy; bỏ quyền đọc của IT cũ vì quyền kỹ thuật không phải nhu cầu nghiệp vụ (yêu cầu chủ dự án), nhưng đây là **lệch có chủ ý so với legacy** và phải được duyệt; A2 nếu chủ bảo mật/khách hàng muốn giữ đúng legacy. Số công ngân sách không chứa lương/chi phí → NỘI BỘ. |
| Phân loại | **CUSTOMER_OR_SECURITY_OWNER_REQUIRED — BLOCKING M1** — duyệt bởi **BOTH**: chủ bảo mật (nhóm xem, phân loại, việc bỏ quyền đọc của IT cũ / IT Support) và khách hàng (xác nhận nhóm người dùng). AppAdmin: DENY trong mọi phương án. **Không** RESOLVED_BY_EVIDENCE; chưa phương án nào được phê duyệt. |
| Mặc định | **BLOCK / KHÔNG ĐOÁN**. |
