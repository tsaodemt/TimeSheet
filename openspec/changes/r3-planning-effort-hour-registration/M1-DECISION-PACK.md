# Gói quyết định M1 — S12.5 Đăng ký công (Hour Registration)

Trạng thái: **CHUẨN BỊ QUYẾT ĐỊNH — CHƯA TRIỂN KHAI.** Nền tảng: Open Spec V3 đã được phê duyệt (R3-G0 = APPROVED,
2026-10-09). READY_FOR_IMPLEMENTATION = NO. Cổng M1 vẫn **BLOCKED** cho tới khi mọi quyết định M1 có câu trả lời ghi nhận
(ngày, người quyết định, nguồn). Đề xuất bên dưới **chưa được phê duyệt**; nếu không có câu trả lời: **BLOCK / KHÔNG ĐOÁN**.

Nhãn bằng chứng: **LEGACY_FACT** (đã kiểm chứng trong mã nguồn legacy dịch ngược hoặc dữ liệu legacy) ·
**TARGET_SECURITY_REQUIREMENT** (kiến trúc bảo mật mục tiêu đã duyệt) · **OWNER_PROVIDED_REQUIREMENT** (yêu cầu/quyết
định của chủ dự án đã ghi nhận) · **PROPOSED_MODERNIZATION** (đề xuất của đặc tả, chưa duyệt) · **OPEN_BUSINESS_DECISION**.

## 0. Tóm tắt phân loại

| Phân loại | Số | ID |
|---|---|---|
| RESOLVED_BY_EVIDENCE (đề xuất đóng bằng bằng chứng; chủ dự án xác nhận khi duyệt gói này) | 3 | OD-02, OD-04, OD-09 |
| Chủ dự án quyết định nội bộ (không cần hỏi khách hàng) | 3 | OD-01, OD-03, OD-05 |
| Cần khách hàng trả lời (phán đoán nghiệp vụ thật sự) | 3 | OD-25, OD-07, OD-08 |
| Có điều kiện (trở nên không liên quan nếu OD-25 = b) | 6 | OD-01, OD-02, OD-03, OD-07, OD-08, OD-09 |

**Quyết định M1 còn chặn sau gói này: 6** (OD-01, OD-03, OD-05, OD-07, OD-08, OD-25). Ba mục đóng bằng bằng chứng chỉ
được chuyển sang "RESOLVED_BY_EVIDENCE" trong `decisions.md` sau khi chủ dự án chấp thuận gói này.

## 1. Thứ tự & phụ thuộc

```text
OD-25 (quan hệ màn hình cũ ↔ Đăng ký công rev01)  ← hỏi TRƯỚC
  ├─ nếu (a) tách riêng / (c) mở rộng: tiếp tục các câu dưới cho ma trận S12.5
  └─ nếu (b) A.I thay thế S12.5: OD-01, 02, 03, 07, 08, 09 hết hiệu lực cho M1 → đặc tả S12.5 phải làm lại
OD-02 (dòng = giai đoạn của dự án) → OD-08 (giá trị trên giai đoạn bị gỡ) chỉ có nghĩa khi dòng theo dự án
OD-01 (trống ≠ 0) → OD-09 (xóa ô lưu gì): biểu diễn "trống" phụ thuộc OD-01
OD-03, OD-04, OD-05, OD-07: độc lập
```

---

## OD-25 — Màn hình "Đăng ký công" cũ và yêu cầu mới "Đăng ký công – rev01" (mục A.I) có phải là một?

| Mục | Nội dung |
|---|---|
| Câu hỏi nghiệp vụ | Ma trận "Công đăng ký cho dự án" của phần mềm cũ (dự án × giai đoạn × bộ môn) và việc PM đăng ký công dự án cho Quản lý phòng, PM, các bộ môn trong tài liệu rev01 là **cùng một chức năng**, hay hai chức năng khác nhau? |
| Vì sao cần | Quyết định có xây S12.5 theo dạng cũ hay không. Hỏi sai thứ tự có thể làm hai lần cùng một thứ hoặc chuyển 199 ô dữ liệu cũ vào sai chỗ. |
| Legacy thực tế (LEGACY_FACT) | Màn hình cũ: chọn dự án → ma trận giai đoạn của dự án × 5 bộ môn (Điện, Lạnh, Nước, BIM, **QL**), đơn vị "công"; ngân sách trọn đời dự án; không duyệt, không khóa. Người ghi: CEO, Thư ký, PM (+ Admin). Báo cáo so "Công đăng ký" với "Công thực hiện". |
| Rev01 (OPEN_BUSINESS_DECISION) | A.I: "Người thực hiện: PM; Dữ liệu: từ bảng phân bổ sản lượng dự án; Công đăng ký: cho Quản lý phòng, PM, bộ môn (điện, lạnh, nước, BIM)". Không nhắc giai đoạn. Dự án phân loại rev01 là **yêu cầu mới**. |
| Đặc tả hiện cho phép | Giữ tách riêng cho tới khi có quyết định; có liên kết tùy chọn. |
| Phương án A | **Tách riêng**: S12.5 = ma trận ngân sách cũ (giữ báo cáo cũ, chuyển 199 ô); A.I là chức năng mới làm ở M2 (có thể lấy số từ S12.5 nếu M2 quyết định). |
| Phương án B | **A.I thay thế S12.5**: không xây ma trận cũ; M1 chuyển thành A.I (cần các quyết định M2 về đơn vị, kỳ, nguồn bảng phân bổ). |
| Phương án C | **Mở rộng chung**: một thực thể duy nhất, ma trận cũ được bổ sung cột QLP/PM và quy tắc rev01. |
| Đề xuất | **A** |
| Lý do | Không có yêu cầu khách hàng nói A.I thay thế màn hình cũ; ngữ nghĩa cũ (theo giai đoạn, trọn đời) đã kiểm chứng và đang dùng cho báo cáo; A cho phép giao S12.5 sớm như kế hoạch mà không chặn M2. |
| Ảnh hưởng nghiệp vụ | A: người dùng có lại màn hình quen thuộc ngay; A.I đến sau. B: mất ma trận theo giai đoạn nếu rev01 không có giai đoạn. |
| Ảnh hưởng UX | A: một màn hình S12.5 + một màn hình A.I sau. B/C: một màn hình, thiết kế lại. |
| Dữ liệu/chuyển đổi | A: chuyển 199 ô sang `HourRegistrations`. B: có thể không chuyển hoặc chuyển vào thực thể A.I (cần quy tắc). |
| Bảo mật | Không đổi nguyên tắc (ghi qua luồng có kiểm soát). |
| Nếu từ chối A | M1 phải chờ các quyết định M2 (OD-14, 16, 22, 23, 24, 40); tiến độ S12.5 03–05/11 (mục tiêu do chủ dự án cung cấp) không giữ được. |
| Ai quyết | **Khách hàng** (CEO + PMO). |
| Mặc định nếu chưa trả lời | **BLOCK / KHÔNG ĐOÁN** |

## OD-01 — Ô trống và số 0 có khác nhau không?

| Mục | Nội dung |
|---|---|
| Câu hỏi | Khi PM nhập "0" vào một ô, hệ thống mới có phải giữ "0" (đã đăng ký là 0) khác với ô để trống (chưa đăng ký) không? |
| Vì sao cần | Quyết định cách lưu, giao diện, kiểm thử khứ hồi và cách chuyển 4 ô "0" cũ. |
| Legacy thực tế (LEGACY_FACT) | Tệp lưu **có** phân biệt "" và "0" (4 ô "0" tồn tại), nhưng màn hình **hiện 0 thành trống** và lần lưu sau ghi thành trống; báo cáo cộng cả hai như 0. Người dùng cũ chưa bao giờ thấy "0" được giữ. |
| Đặc tả hiện cho phép | Hai phương án; backlog dự án ghi "trống ≠ 0" (PROPOSED_MODERNIZATION, không phải yêu cầu khách hàng). |
| Phương án A | **Trống ≠ 0**: giữ cả hai trạng thái khi lưu, hiển thị, khứ hồi; báo cáo vẫn cộng trống như 0. |
| Phương án B | **Như cũ**: 0 và trống tương đương. |
| Đề xuất | **A** |
| Lý do | Bảo toàn dữ liệu (không mất thông tin "đã đăng ký 0"); báo cáo cho kết quả **giống hệt** legacy vì trống và 0 đều cộng 0 → không thay đổi ngữ nghĩa nghiệp vụ nào người dùng đang dựa vào. |
| Ảnh hưởng nghiệp vụ | Không đổi tổng; chỉ thêm khả năng phân biệt. |
| UX | Ô trống hiện "—"/rỗng, ô 0 hiện "0". |
| Dữ liệu | A: 4 ô "0" cũ chuyển thành 0, 271 ô trống không tạo bản ghi. B: 4 ô "0" có thể chuyển thành trống. |
| Bảo mật | Không. |
| Nếu từ chối A | Áp dụng B; đặc tả mục 9.5 và AC-REG-01/10 dùng nhánh B. |
| Ai quyết | **Chủ dự án nội bộ** (không thay đổi kết quả nghiệp vụ hiện có); khách hàng chỉ cần được thông báo. |
| Mặc định | **BLOCK / KHÔNG ĐOÁN** |

## OD-02 — Dòng của ma trận: giai đoạn của dự án hay tất cả giai đoạn?

| Mục | Nội dung |
|---|---|
| Câu hỏi | Ma trận hiển thị các giai đoạn đã gán cho dự án (theo thứ tự của dự án) hay tất cả giai đoạn trong danh mục? |
| Legacy thực tế (LEGACY_FACT) | Dòng = **các giai đoạn của dự án được chọn**, theo thứ tự của dự án; dự án không có giai đoạn thì ma trận trống. Tài liệu phân tích cũ ghi nhầm "tất cả giai đoạn". |
| Đặc tả hiện cho phép | Mặc định đề xuất cũ UD-07 "tất cả giai đoạn hoạt động" (PROPOSED_MODERNIZATION, không phải yêu cầu khách hàng). |
| Phương án A | Giai đoạn của dự án (như cũ). |
| Phương án B | Tất cả giai đoạn hoạt động (có nút chuyển). |
| Phân loại | **RESOLVED_BY_EVIDENCE → A** |
| Lý do | Không có yêu cầu khách hàng thay đổi; hành vi cũ đã kiểm chứng; đăng ký công cho giai đoạn không thuộc dự án không có nghĩa nghiệp vụ; UD-07 chỉ là đề xuất của nhóm phân tích dựa trên mô tả sai. |
| UX / dữ liệu | Ma trận nhỏ (thực tế tối đa 6 × 5; danh mục 13 × 5). Dữ liệu cũ khớp hoàn toàn. |
| Nếu chủ dự án không chấp thuận | Trả về câu hỏi khách hàng. |
| Ai quyết | Chủ dự án xác nhận bằng chứng. |

## OD-03 — Giá trị hợp lệ của một ô

| Mục | Nội dung |
|---|---|
| Câu hỏi | Ô nhận số nguyên hay số lẻ? bao nhiêu chữ số thập phân? giới hạn nào? |
| Legacy thực tế (LEGACY_FACT) | Ô là văn bản tự do, **không kiểm tra**; chữ hoặc số âm bị âm thầm biến thành trống khi tải lại. Phần mềm cũ **đọc được số lẻ** (dấu chấm), báo cáo hiển thị 2 chữ số thập phân. Dữ liệu thực tế: chỉ số nguyên 2–200, chưa từng có số lẻ, số âm hay chữ. |
| Đặc tả hiện cho phép | Đề xuất ≥ 0, tối đa 1 chữ số thập phân, ≤ 999,9 (PROPOSED_MODERNIZATION). |
| Phương án A | Số không âm, tối đa **2** chữ số thập phân, tối đa 9.999 (giữ khả năng số lẻ của legacy và định dạng 2 số lẻ của báo cáo). |
| Phương án B | Số nguyên không âm 0–999. |
| Đề xuất | **A** |
| Lý do | Không tước khả năng nhập số lẻ mà legacy có; giới hạn chỉ chặn dữ liệu rác (lỗi legacy cần sửa); giới hạn trên rộng để không chặn dự án lớn. |
| Ảnh hưởng | Nhập sai bị báo lỗi ngay (thay vì mất âm thầm). Dữ liệu cũ đều hợp lệ. |
| Nếu từ chối A | Áp dụng B hoặc phương án chủ dự án chỉ định; đặc tả và kiểm thử điều chỉnh. |
| Ai quyết | **Chủ dự án nội bộ** (quy tắc chất lượng dữ liệu, không đổi ngữ nghĩa). |
| Mặc định | **BLOCK / KHÔNG ĐOÁN** |

## OD-04 — Ai được sửa / xóa ô / lưu ma trận?

| Mục | Nội dung |
|---|---|
| Legacy thực tế (LEGACY_FACT) | Quyền GHI: CEO, Thư ký, PM; Admin bỏ qua kiểm tra quyền (kỹ thuật). Mọi kiểm tra ở phía máy người dùng. |
| Ánh xạ vai trò mục tiêu (đã có trong mô hình vai trò) | CEO → Executive; PM và Thư ký → PMO (PMO có "hour registration"); Admin → App Administrator. |
| Yêu cầu chủ dự án (OWNER_PROVIDED_REQUIREMENT) | "Không cấp quyền nghiệp vụ cho AppAdmin chỉ vì là quản trị kỹ thuật" (phạm vi R3). |
| Phương án A | Executive + PMO. |
| Phương án B | Executive + PMO + AppAdmin. |
| Phân loại | **RESOLVED_BY_EVIDENCE → A** |
| Lý do | Người ghi nghiệp vụ của legacy ánh xạ đúng sang Executive + PMO; quyền Admin của legacy là cơ chế bỏ qua kỹ thuật, bị loại bởi yêu cầu chủ dự án; bảo mật mục tiêu kiểm tra phía máy chủ. |
| Bảo mật | Ghi chỉ qua luồng có kiểm soát; AppAdmin bị từ chối (ROLE_NOT_ALLOWED). Cần sửa seed vai trò (hiện cấp `REG.Edit` cho AppAdmin) khi triển khai. |
| Ai quyết | Chủ dự án xác nhận bằng chứng. |

## OD-05 — Ai được xem ma trận; mức phân loại dữ liệu

| Mục | Nội dung |
|---|---|
| Legacy thực tế (LEGACY_FACT) | Xem: Manager, Leader, IT, HRD (+ người có quyền ghi); Ẩn: Member, AD (kế toán). Director không có dòng quyền (vai trò đã bỏ). Phân loại tệp: nội bộ. |
| Ánh xạ mục tiêu | Manager → Approver; Leader → Team Leader; HRD → HR; Member → Employee (ẩn); AD → Finance (ẩn); **IT → ?** (AppAdmin hoặc IT Support). |
| Đặc tả hiện cho phép | Seed hiện: TL, APR, EXE, PMO, HR, **ADM** xem; một tài liệu đề xuất phân loại "Mật (ngân sách)". |
| Phương án A | Xem: TL, APR, EXE, PMO, HR; **không** cho ADM/IT Support; phân loại NỘI BỘ trên site vận hành. |
| Phương án B | Như A nhưng giữ quyền xem cho AppAdmin (tương ứng IT cũ). |
| Phương án C | Phân loại MẬT → đặt ở vùng dữ liệu mật (phụ thuộc quyết định ENV-D2 chưa có). |
| Đề xuất | **A** |
| Lý do | Giữ đúng nhóm người dùng nghiệp vụ của legacy; số công ngân sách không chứa lương/chi phí nên NỘI BỘ là đủ (như legacy); quản trị kỹ thuật không cần xem dữ liệu nghiệp vụ (cùng nguyên tắc với OD-04). |
| Bảo mật | Người dùng thường không đọc/ghi trực tiếp danh sách; xem qua luồng đọc có kiểm soát. |
| Nếu từ chối A | B: thêm ADM vào ma trận quyền; C: M1 phụ thuộc ENV-D2 (chậm). |
| Ai quyết | **Chủ dự án nội bộ** (cùng HR nếu cần) — kiến trúc quyền & phân loại. |
| Mặc định | **BLOCK / KHÔNG ĐOÁN** |

## OD-07 — Dự án ngưng/đóng có được hiển thị và sửa ngân sách không?

| Mục | Nội dung |
|---|---|
| Legacy thực tế (LEGACY_FACT) | Liệt kê **mọi** dự án (cờ lọc là trạng thái giao diện, luôn bật) và cho sửa; legacy không có khái niệm dự án đóng trên màn hình này. |
| Đặc tả hiện cho phép | Danh mục dự án mục tiêu có trạng thái (ví dụ Active); chưa quyết định cho Đăng ký công. |
| Phương án A | Như cũ: liệt kê và sửa mọi dự án. |
| Phương án B | Dự án hoạt động: sửa được; dự án khác: chỉ xem. |
| Phương án C | Chỉ liệt kê dự án hoạt động. |
| Đề xuất | **A** (giữ ngữ nghĩa legacy; B là lựa chọn kiểm soát nếu khách hàng muốn khóa ngân sách dự án đã đóng). |
| Lý do | Không có yêu cầu khách hàng; ưu tiên ngữ nghĩa legacy trước tính toàn vẹn. |
| Ảnh hưởng | B/C giảm sai sót trên dự án đã đóng nhưng có thể chặn điều chỉnh cuối dự án. |
| Ai quyết | **Khách hàng** (PMO). |
| Mặc định | **BLOCK / KHÔNG ĐOÁN** |

## OD-08 — Số đã đăng ký trên giai đoạn bị gỡ khỏi dự án / bộ môn ngưng dùng

| Mục | Nội dung |
|---|---|
| Legacy thực tế (LEGACY_FACT) | Dòng của giai đoạn đã gỡ bị **ẩn**, vẫn nằm trong tệp và **vẫn được cộng** trong báo cáo toàn dự án cho tới lần lưu kế tiếp, khi đó **bị xóa âm thầm** (lỗi mất dữ liệu). Bộ môn: legacy hiện mọi bộ môn trong danh mục (không lọc hoạt động). Dữ liệu: 1 dự án có 1 dòng như vậy (toàn ô trống, không mất giá trị). |
| Quyết định dự án liên quan | D-7 (đã duyệt): không xóa cứng, chỉ xóa mềm → loại phương án "xóa". |
| Phương án A | Giữ, hiện ở chế độ chỉ xem có đánh dấu "giai đoạn không còn trong dự án", **vẫn tính** trong tổng toàn dự án. |
| Phương án B | Giữ nhưng ẩn và **không tính** trong tổng. |
| Đề xuất | **A** |
| Lý do | Không mất dữ liệu (sửa lỗi legacy), tổng toàn dự án giống báo cáo legacy (vốn vẫn cộng các dòng này), người dùng thấy rõ và tự xử lý. |
| UX | Thêm dòng/cột chỉ xem có nhãn. |
| Dữ liệu | Chuyển đổi: dòng cũ giữ nguyên với nhãn. |
| Ai quyết | **Khách hàng** (PMO) — có tính số này vào tổng hay không là phán đoán nghiệp vụ. |
| Điều kiện | Chỉ có nghĩa khi OD-02 = A (dòng theo giai đoạn của dự án). |
| Mặc định | **BLOCK / KHÔNG ĐOÁN** |

## OD-09 — Khi xóa (làm trống) một ô thì lưu gì?

| Mục | Nội dung |
|---|---|
| Legacy thực tế (LEGACY_FACT) | Delete/Backspace làm trống ô; lưu ghi đè cả tệp (không lịch sử). |
| Quyết định dự án (OWNER_PROVIDED_REQUIREMENT / TARGET_SECURITY_REQUIREMENT) | D-7: nghiệp vụ chỉ xóa mềm; tài khoản dịch vụ **không bao giờ** có quyền Delete. |
| Phương án A | Giữ bản ghi, đặt giá trị = rỗng (null); lịch sử nằm trong version và audit. |
| Phương án B | Thêm cờ xóa mềm trên bản ghi. |
| Phương án C | Xóa bản ghi (cần quyền Delete) — **bị loại bởi D-7**. |
| Phân loại | **RESOLVED_BY_EVIDENCE → A** |
| Lý do | C vi phạm D-7; B thêm một trạng thái không có ý nghĩa nghiệp vụ (trùng nghĩa với "trống"); A là cách duy nhất đáp ứng D-7 mà không thêm quy trình. Đây là lựa chọn kỹ thuật, không phải sở thích nghiệp vụ. |
| Phụ thuộc | Biểu diễn "trống" theo OD-01 (A: null ≠ 0; B: tương đương). |
| Ai quyết | Chủ dự án xác nhận bằng chứng. |
