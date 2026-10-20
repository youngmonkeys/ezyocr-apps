# Trạm nhận diện vận đơn

Ứng dụng desktop cho trạm kho: mở một cửa sổ web (trang trạm của ezyplatform), sau khi nhân viên đăng nhập thì bật camera, đọc barcode và OCR nhãn vận đơn Trung Quốc bằng PaddleOCR (engine ONNX Runtime) + zxing-cpp, trích mã vận đơn và mã khách, đẩy kết quả cho trang trạm (trang tự gửi lên ezyplatform) và in tem theo yêu cầu. Thiết kế chi tiết: [docs/thiet-ke-he-thong.md](docs/thiet-ke-he-thong.md).

Đóng gói cho macOS (`.app` trong file `.dmg`) và Windows (bộ cài `.msi`).

## Cấu trúc thư mục

```
OCRs/
├── pyproject.toml               # metadata, dependencies, cấu hình đóng gói Briefcase
├── src/ezyocr/         # mã nguồn ứng dụng
│   ├── __main__.py              # điểm vào: python -m ezyocr
│   ├── app.py                   # cửa sổ pywebview, menu, vòng đời dịch vụ
│   ├── bridge.py                # API cho JavaScript: window.pywebview.api.*
│   ├── session.py               # theo dõi cookie accessToken của ezyplatform
│   ├── ezyplatform.py           # đăng nhập admin ezyplatform, gọi API script nghiệp vụ
│   ├── business/                # script nghiệp vụ: lớp cơ sở, script mặc định waybill_cn, kho script đã tải, bộ nạp
│   ├── core.py                  # lõi nhận diện: camera → OCR → hàng đợi → trang trạm
│   ├── settings.py              # cấu hình trạm (đọc/ghi settings.json)
│   ├── i18n.py                  # đa ngôn ngữ (vi, en, zh), bản dịch ở resources/i18n/
│   ├── paths.py                 # thư mục dữ liệu, log, tài nguyên
│   ├── log.py                   # ghi log ra file xoay vòng
│   ├── camera/scanner.py        # đọc camera, chờ barcode + ảnh đứng yên, dự phòng OCR khi không đọc được barcode
│   ├── recognition/             # backend OCR (backends/), quy tắc trích mã vận đơn và mã khách
│   ├── storage/outbox.py        # hàng đợi SQLite, giữ kết quả tới khi trang trạm xác nhận đã gửi
│   ├── storage/uploads.py       # hàng đợi SQLite của ảnh chờ upload và chờ gắn vào vận đơn
│   ├── upload/                  # upload ảnh lên media ezyplatform, gắn media vào vận đơn ezydelivery
│   ├── printing/                # dựng lệnh ZPL/TSPL gửi thẳng ra máy in; in trang HTML khi trang gọi window.open('') + print()
│   └── resources/               # cấu hình mặc định, trang cài đặt, model OCR (tải bằng script)
├── scripts/
│   ├── fetch_models.py          # tải model OCR vào resources/models để đóng gói
│   ├── make_icon.py             # tạo bộ icon EzyOCR (.icns, .ico, .png)
│   ├── build_macos.sh           # đóng gói .app + .dmg
│   └── build_windows.ps1        # đóng gói bộ cài .msi cho Windows
├── tools/
│   ├── ocr_demo.py              # chạy nhận diện hàng loạt trên thư mục ảnh
│   └── make_sample.py           # tạo ảnh mẫu tiếng Việt
├── packaging/icons/             # icon sinh ra bởi make_icon.py
├── images/                      # ảnh vận đơn mẫu
└── docs/                        # tài liệu thiết kế
```

## Cài đặt môi trường phát triển

Yêu cầu: Python 3.12 và [uv](https://docs.astral.sh/uv/) (hoặc `pip`).

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Lệnh trên cài ứng dụng ở chế độ editable (sửa code là có hiệu lực ngay) kèm Briefcase để đóng gói.

## Chạy ứng dụng từ mã nguồn

```bash
python -m ezyocr            # hoặc: ezyocr
python -m ezyocr --setup    # mở thẳng trang cài đặt trạm
python -m ezyocr --debug    # log chi tiết, bật công cụ dev của webview
python -m ezyocr --camera-test   # thử camera và nhận diện trên máy, không cần đăng nhập hay server
```

Chế độ `--camera-test` bật camera ngay (mặc định camera số 0, trên Mac là camera tích hợp), hiện khung xem trước, tự nhận diện mỗi khi có vật mới đặt vào và khung hình đứng yên (bật "Chỉ nhận diện khi thấy barcode" để giống trạm thật), có nút "Chụp ngay" để nhận diện khung hình hiện tại và nút "Nhận diện từ ảnh…" để chọn một file ảnh (jpg, png, bmp, webp, tif) trên máy rồi nhận diện như ảnh chụp từ camera, tiện khi chưa có nhãn in để thử; nút này cũng có ở cửa sổ **Xem camera nhận diện** của ca làm việc, khi đó kết quả được gửi sang trang làm việc như khi bấm "Chụp ngay". Đọc đủ mã vận đơn và mã khách thì phát âm `sound.success`, thiếu một trong hai thì phát `sound.warning` (đổi file âm thanh hoặc tắt trong `settings.json`). Kết quả chỉ hiện trên cửa sổ, không vào hàng đợi. Ảnh chụp vẫn lưu vào thư mục ảnh nếu bật lưu ảnh. Khi chạy từ terminal, macOS hỏi quyền camera cho ứng dụng terminal (Terminal hoặc VS Code).

Lần đầu mở, ứng dụng đi qua 3 bước: chọn ngôn ngữ (chọn sẵn ngôn ngữ của máy; chọn ngôn ngữ khác thì app tự mở lại để đổi ngôn ngữ menu), đăng nhập ezyplatform (địa chỉ trang admin, tên đăng nhập, mật khẩu), rồi trang **Cài đặt trạm** đầy đủ (camera, script nghiệp vụ, mô hình nhận diện, máy in, lưu ảnh). App đăng nhập bằng `POST /login` của admin, rồi đưa token vào cửa sổ qua `GET /api/v1/admins/me/access-token/fetch-to-cookie` nên sau khi lưu, cửa sổ mở trang làm việc mà không phải đăng nhập lại. Mật khẩu không được lưu. Tài khoản bật xác thực 2 lớp chưa được hỗ trợ. Mở lại trang cài đặt bằng menu **Trạm → Cài đặt trạm…**; đăng xuất ở mục **Tài khoản** sẽ xoá dữ liệu web của cửa sổ và quay về bước đăng nhập.

Giao diện có 3 ngôn ngữ: Tiếng Việt, English, 中文 (giản thể). Chọn ở menu **Trợ giúp → Ngôn ngữ** hoặc trang **Cài đặt trạm** (mục `language` trong `settings.json`: `auto`, `vi`, `en`, `zh`); `auto` lấy theo ngôn ngữ của hệ điều hành, không khớp thì dùng English. Bản dịch nằm ở `src/ezyocr/resources/i18n/*.json`. Khi lưu cài đặt mà ngôn ngữ thay đổi, ứng dụng hỏi có khởi động lại ngay không (menu và nút trên thanh tiêu đề chỉ đổi ngôn ngữ sau khi khởi động lại); chọn "Để sau" thì các trang đổi ngôn ngữ ngay, menu đổi ở lần mở sau. Trang trạm có thể hỏi ngôn ngữ đang dùng qua `window.pywebview.api.get_language()`.

Tiêu đề cửa sổ hiện địa chỉ trang đang mở. Khi cần gửi màn hình đang gặp lỗi cho bộ phận hỗ trợ, dùng menu **Trạm → Sao chép địa chỉ trang** rồi dán vào tin nhắn. Menu **Trạm** cũng có **Tải lại trang** và **Quay lại**.

Khi quét mà không thấy kết quả, bấm icon camera trên thanh tiêu đề (hoặc menu **Trạm → Xem camera nhận diện**) để mở cửa sổ xem trực tiếp camera của ca làm việc: trạng thái bộ nhận diện, camera, đăng nhập, số kết quả chờ gửi, kết quả từng kiện kèm chữ OCR đọc được và nút "Chụp ngay". Khung hình chỉ được gửi sang cửa sổ này khi nó đang mở; đóng cửa sổ không ảnh hưởng tới ca làm.

Khi chạy từ mã nguồn mà chưa chạy `scripts/fetch_models.py`, PaddleOCR tự tải model ở lần đầu (cần mạng).

## Chọn mô hình nhận diện

Trang **Cài đặt trạm** có mục **Nhận diện chữ** để chọn mô hình OCR (`ocr.backend` trong `settings.json`), kèm trạng thái của bộ nhận diện đang chạy và thời gian nhận diện trung bình. Lưu xong, bộ nhận diện được nạp lại ở luồng nền (trạm báo `loading` như lúc khởi động), không cần khởi động lại ứng dụng. Danh sách chỉ hiện các mô hình có thư viện trong bản cài; mô hình đang cấu hình mà bản cài không có thì hiện kèm chú thích và không lưu được cho tới khi chọn mô hình khác.

| `ocr.backend` | Thư viện cần có | Ghi chú |
|---|---|---|
| `paddleocr` (mặc định) | `paddleocr` | Giữ nguyên hành vi cũ, dùng model đóng gói sẵn trong `resources/models` |
| `rapidocr` | `pip install -e ".[rapidocr]"` | Model PP-OCR dạng ONNX chạy bằng `onnxruntime`, nhẹ và khởi động nhanh hơn. Lần đầu tự tải model nếu chưa có |
| `apple_vision` | `pip install -e ".[apple-vision]"` (macOS) | OCR của hệ điều hành, không cần model. Tiếng Trung cần macOS 13 trở lên |
| `windows_ocr` | `pip install -e ".[windows-ocr]"` (Windows) | `Windows.Media.Ocr`, không cần model. Phải cài gói ngôn ngữ tương ứng trong **Settings → Time & language → Language & region**. Không trả độ tin cậy nên `score` luôn là 1 |
| `tesseract` | `pip install -e ".[tesseract]"` và chương trình `tesseract` kèm dữ liệu ngôn ngữ | Phù hợp nhãn chữ Latin đơn giản |

Tham số riêng của từng mô hình đặt trong `ocr.options`, theo tên mô hình (không có trên trang cài đặt):

```json
"ocr": {
  "backend": "paddleocr",
  "options": {
    "paddleocr": {"lang": "ch", "ocr_version": "PP-OCRv5", "text_recognition_model_dir": "/duong/dan/model"},
    "rapidocr": {"config_path": "/duong/dan/config.yaml", "params": {}},
    "apple_vision": {"languages": ["zh-Hans", "en-US"], "recognition_level": "accurate", "language_correction": false},
    "windows_ocr": {"language": "zh-Hans-CN"},
    "tesseract": {"lang": "chi_sim+eng", "config": "", "tesseract_cmd": ""}
  },
  "use_doc_orientation_classify": true
}
```

Mọi mô hình trả về cùng kiểu `Line(text, score, box)`: `box` là tọa độ pixel trên ảnh gốc, `score` trong khoảng 0..1, nên quy tắc trích trường trong `recognition/extract.py` dùng chung được. Thêm mô hình mới: tạo lớp con `OcrBackend` trong `recognition/backends/` (`available()`, `load(options)`, `read_lines(image)`) rồi đăng ký trong `recognition/backends/__init__.py`. Muốn bản cài kèm thêm mô hình nào thì thêm thư viện của mô hình đó vào `dependencies` trước khi build.

## Đóng gói cho macOS

```bash
source .venv/bin/activate
scripts/build_macos.sh
```

Script tự làm các bước:

1. Tải model OCR vào `src/ezyocr/resources/models/` nếu chưa có (cần mạng, khoảng 140 MB), để bản cài chạy được không cần mạng.
2. Tạo icon `packaging/icons/ezyocr.icns` nếu chưa có.
3. Dùng Briefcase tạo hoặc cập nhật app bundle trong `build/`, build, rồi đóng gói ra `dist/*.dmg`.

Mặc định app được ký ad-hoc, chạy được trên máy build. Để phát cho máy khác mà không bị Gatekeeper chặn, cần chứng chỉ Developer ID của Apple:

```bash
SIGN_IDENTITY="Developer ID Application: Ten Cong Ty (TEAMID)" scripts/build_macos.sh
```

Briefcase sẽ ký và notarize. Nếu chưa có chứng chỉ, trên máy khác mở app lần đầu bằng chuột phải → **Open**, hoặc chạy `xattr -dr com.apple.quarantine "/Applications/Trạm nhận diện.app"`.

Bản build chỉ dành cho kiến trúc của máy build (Intel hoặc Apple Silicon), vì `paddlepaddle`, `onnxruntime` và `opencv` không có bản universal2.

### Người dùng cài đặt

1. Mở file `.dmg`, kéo **Trạm nhận diện** vào **Applications**.
2. Mở app, cho phép dùng camera khi macOS hỏi.
3. Lần đầu: chọn ngôn ngữ, đăng nhập ezyplatform, rồi chỉnh cài đặt trạm.
4. Hằng ngày: mở app, đặt kiện dưới camera. App giữ đăng nhập và mở lại trang đang dùng lần trước; chỉ phải đăng nhập lại khi token admin hết hạn.

## Đóng gói cho Windows

Phải build trên máy Windows 64-bit (x64), Briefcase không build chéo từ macOS. Yêu cầu: Python 3.12 bản 64-bit (cài từ python.org, tích **Add python.exe to PATH**) và mạng để tải thư viện, model OCR và WiX. Không cần Visual Studio.

Chép mã nguồn vào ổ đĩa của máy Windows (ví dụ `C:\src\OCRs`), không build trực tiếp trong thư mục chia sẻ của máy ảo, rồi chạy trong PowerShell:

```powershell
cd C:\src\OCRs
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

Script tự tạo `.venv` (dùng `uv` nếu có, không thì `py -3.12`) và cài dependencies nếu chưa có, tải model OCR, tạo icon nếu thiếu, rồi dùng Briefcase tạo, build và đóng gói ra `dist\EzyOCR-<version>.msi`. Bộ cài không được ký số nên Windows SmartScreen sẽ cảnh báo khi mở: bấm **More info → Run anyway**. Có chứng chỉ ký mã thì truyền thumbprint SHA-1 qua biến `SIGN_IDENTITY`.

Chạy thử từ mã nguồn trên Windows (sau khi script đã tạo `.venv`):

```powershell
.venv\Scripts\python -m ezyocr --camera-test
```

Khác biệt so với bản macOS:

- In tem gửi lệnh ZPL/TSPL dạng RAW qua spooler của Windows (`pywin32`), `printer.name` là tên máy in trong **Settings → Bluetooth & devices → Printers & scanners**, để trống là máy in mặc định.
- Phiếu HTML in qua hộp thoại in của WebView2, chưa áp dụng `printer.page_printer_name` và `printer.show_print_dialog`.
- Âm thanh mặc định lấy từ `C:\Windows\Media` (`chimes.wav`, `Windows Exclamation.wav`).
- Chưa có nút trên thanh tiêu đề và mục bật/tắt camera trong menu, mở cửa sổ camera bằng menu **Trạm → Xem camera nhận diện**.
- Cửa sổ dùng Microsoft Edge WebView2, có sẵn trên Windows 11.

## Dữ liệu của ứng dụng trên máy

Trên Windows, các file dưới đây nằm trong `%LOCALAPPDATA%\EzyOCR\` (log ở thư mục con `logs\`).


| Đường dẫn | Nội dung |
|---|---|
| `~/Library/Application Support/EzyOCR/settings.json` | Cấu hình trạm (ghi đè lên `resources/default_settings.json`) |
| `~/Library/Application Support/EzyOCR/outbox.sqlite3` | Kết quả trang trạm chưa xác nhận đã gửi lên server (bảng `outbox`), ảnh chưa upload hoặc chưa gắn vào vận đơn (bảng `uploads`) |
| `~/Library/Application Support/EzyOCR/last_page.txt` | Trang làm việc đang mở lần trước, để mở lại khi khởi động |
| `~/Library/Application Support/EzyOCR/business_scripts/<id>/` | Script nghiệp vụ đã tải: `script.py` và `meta.json` (tiêu đề, thời gian cập nhật trên ezyplatform, SHA-256). Hash được kiểm lại mỗi lần nạp |
| `~/Library/Application Support/EzyOCR/captures/` | Thư mục ảnh mặc định: ảnh chụp từng kiện (tên file là `image_id`), thư mục con `debug/` chứa ảnh không đọc được barcode khi chạy `--debug`. Đổi thư mục ở trang **Cài đặt trạm** (`camera.captures_dir`). Khi `camera.save_captures` là `false`, ảnh chỉ nằm đây tới khi gắn xong vào vận đơn. Ảnh cũ hơn `camera.captures_keep_days` ngày (mặc định 30, `0` là không xoá) tự bị xoá mỗi giờ, trừ ảnh còn chờ upload |
| `~/Library/Application Support/EzyOCR/paddlex/` | Cache của PaddleX, trỏ tới model đóng gói sẵn |
| `~/Library/Logs/EzyOCR/station.log` | Log, xoay vòng 5 file × 5 MB |

Các tham số chỉ chỉnh trong `settings.json` (không có trên trang cài đặt): độ phân giải camera, `camera.still_ms`, `camera.motion_threshold`, `camera.ocr_fallback_ms` (vật nằm yên quá số ms này mà chưa đọc được barcode thì vẫn chạy OCR; `0` để tắt), khổ tem, `printer.page_printer_name` (máy in cho các phiếu HTML của trang, để trống là máy in mặc định), `printer.show_print_dialog` (đặt `false` để in phiếu HTML thẳng không hiện hộp thoại), nhóm `upload` (đường dẫn API upload ảnh, `max_attempts`; `upload.enabled: false` để tắt upload ảnh), `web.clear_session_on_start` (đặt `true` để mỗi lần mở app phải đăng nhập lại và mở trang làm việc mặc định).

Cài đặt theo nhân viên: nếu admin đăng nhập có quyền `OCR Operator` (`ocr_operator`), mỗi lần bắt đầu phiên app gọi `GET /ezyocr/api/v1/ocr-operators/me/settings` và áp dụng các giá trị trong `settings` (hiện có `requireBarcode`) thay cho `camera.require_barcode` trong `settings.json`. Admin chỉnh cài đặt cho từng nhân viên ở trang **EzyOCR → Cài đặt**, mục **Nhân viên vận hành OCR** (nút bánh răng ở cột hành động); nhân viên không có quyền này hoặc server chưa có API thì app giữ giá trị trong `settings.json`. Sau khi admin sửa cài đặt, nhân viên chọn menu **Trạm → Tải lại cài đặt nhân viên** để áp dụng ngay mà không cần đăng nhập lại; mục **Cài đặt nhân viên** ở cuối trang **Cài đặt trạm** hiển thị các giá trị đang áp dụng và cũng có nút tải lại. Menu **Trạm → Đăng xuất** dừng camera, xoá phiên đăng nhập và quay về bước đăng nhập.

## Script nghiệp vụ

Phần camera, OCR, hàng đợi, upload ảnh và in dùng chung; phần lấy trường nào từ nhãn nằm trong script nghiệp vụ. App có sẵn script mặc định `waybill_cn` (vận đơn Trung Quốc, `src/ezyocr/business/waybill_cn.py`). Script khác lưu dạng bài viết `OCR_BUSINESS_SCRIPT` trên ezyplatform (plugin ezyocr admin) và được tải về ở màn **Tải script từ ezyplatform…** trong trang cài đặt. Chỉ tài khoản có quyền `ocr_business_script_management` mới xem và tải được.

```python
from ezyocr.business import BusinessScript


class ShopeeLabel(BusinessScript):
    name = "shopee_vn"
    key_field = "tracking_number"
    required_fields = ("tracking_number", "customer_code")
    home_path = "/"
    media_link_path = "/ezydelivery/api/v1/delivery-order-codes/{code}/medias/{media_id}"

    def extract(self, ctx):
        return {"tracking_number": ctx.barcode, "customer_code": None}
```

- File script khai báo đúng một lớp kế thừa `BusinessScript`. `extract(ctx)` nhận `ctx.lines` (các dòng OCR: `text`, `score`, toạ độ), `ctx.image` (ảnh numpy) và `ctx.barcode` (barcode camera đọc được), trả về một `dict`.
- `key_field` dùng để chống trùng và đưa vào hàng đợi; đủ mọi trường trong `required_fields` thì phát âm báo thành công, thiếu thì phát âm cảnh báo.
- `home_path` là trang mở sau khi lưu cài đặt (đường dẫn trên trang admin). `media_link_path` là API gắn ảnh vào bản ghi sau khi trang gọi `ack_result`; bỏ trống thì không upload ảnh.
- Script chỉ dùng được thư viện đã đóng gói trong app.
- Trước khi cài, app hiện hộp thoại native với tên, mã, thời gian cập nhật và số dòng thay đổi. Không cho cài bản cũ hơn bản đang có trên máy. Script đang dùng được cập nhật thì app tự nạp lại.
- Script lỗi khi nạp (thiếu file, sai SHA-256, lỗi cú pháp) hoặc lỗi khi nhận diện thì trạm tự chuyển sang script mặc định và báo lỗi (`business_script_error` trong `get_status()`, sự kiện `error`).

## Tích hợp với trang trạm của ezyplatform

Trang trạm chạy trong cửa sổ của ứng dụng nên gọi được các hàm Python qua `window.pywebview.api` (có sau sự kiện `pywebviewready`):

| Hàm | Kết quả |
|---|---|
| `print_label(tracking_number, customer_code)` | `{ok: true}` hoặc `{ok: false, error}`. Bỏ trống `customer_code` thì dùng mã khách lõi nhận diện đọc được |
| `get_status()` | `{test_mode, require_barcode, ocr, ocr_backend, ocr_error, ocr_avg_ms, business_script, business_script_error, camera, running, pending, uploads, configured, version}`. `uploads` là số ảnh chưa gắn xong vào vận đơn, `ocr_avg_ms` là thời gian OCR trung bình mỗi ảnh từ lúc nạp bộ nhận diện |
| `get_pending_results()` | Danh sách bản tin trong hàng đợi chưa được xác nhận, cũ nhất trước (tối đa 100) |
| `ack_result(image_id, code)` | `{ok: true}` hoặc `{ok: false, error}`. Xoá bản tin khỏi hàng đợi và gắn ảnh của nó vào bản ghi `code` theo `media_link_path` của script nghiệp vụ (script mặc định: mã vận đơn). Bỏ trống `code` khi nhân viên bỏ kết quả: ảnh không được gắn |
| `print_html(content, base_url)` | In một trang HTML qua hộp thoại in của hệ điều hành. Trang không cần gọi trực tiếp: ứng dụng tự thay `window.open('')` để các đoạn in kiểu `window.open('')` → `document.write(html)` → `print()` của ezyplatform chạy được trong cửa sổ nhúng (WKWebView không mở cửa sổ mới) |
| `open_setup()` | Mở trang cài đặt trạm |

Ứng dụng phát sự kiện trên `window` cho trang trạm:

```js
window.addEventListener("ezyocr", (e) => {
  const { event, data } = e.detail;
  // event: "status" | "processing" | "result" | "empty" | "error"
});
```

Ứng dụng không tự kết nối tới server. Trang trạm đã đăng nhập sẵn nên tự gửi kết quả lên ezyplatform:

- Sự kiện `result` mang bản tin như mục 8 của tài liệu thiết kế. Bản tin có `tracking_number` được ghi vào hàng đợi SQLite trước khi phát sự kiện.
- Trang gửi bản tin lên server bằng API của ezyplatform; server lưu xong thì trang gọi `ack_result(data.image_id, mã vận đơn đã lưu)` để xoá khỏi hàng đợi. Truyền mã sau khi nhân viên sửa (nếu có), vì ảnh sẽ được gắn vào đúng mã này.
- Khi trang tải xong (sau `pywebviewready`) hoặc có mạng trở lại, trang gọi `get_pending_results()` và gửi bù các bản tin chưa xác nhận. Server chống ghi trùng theo `tracking_number`.
- Ảnh gốc của mỗi kiện có `tracking_number` được upload chạy nền ngay khi chụp xong: `POST /api/v1/media/add?avatar=false&notPublic=true`, tên file `{image_id}.jpg`, header `Authorization: Bearer <token>` lấy từ cookie của cửa sổ. Sau khi trang gọi `ack_result`, ứng dụng gắn media theo `media_link_path` của script nghiệp vụ; script mặc định dùng `PUT /ezydelivery/api/v1/delivery-order-codes/{mã vận đơn}/medias/{mediaId}` (ezydelivery lưu vào `ecommerce_product_medias`, giống official-shipping). Lỗi mạng, 5xx, 401/403 thì gửi lại với thời gian chờ tăng dần (tối đa 10 phút); lỗi 4xx khác thì bỏ sau `upload.max_attempts` lần.
- Vai trò admin của nhân viên trạm cần quyền `media_management` (upload ảnh) và `delivery_order_management` (lưu vận đơn, gắn ảnh).
- Nhân viên đăng xuất hoặc token hết hạn (cookie `accessToken` mất) thì ứng dụng tắt camera; muốn buộc trạm dừng thì server cho trang đăng xuất.

## Chạy nhận diện hàng loạt (demo)

```bash
python tools/ocr_demo.py                                  # toàn bộ ảnh trong images/
python tools/ocr_demo.py images/waybill_sf_01.jpg
python tools/ocr_demo.py /duong/dan/thu-muc-anh
```

Chạy từ thư mục gốc của dự án. Định dạng ảnh hỗ trợ: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`.

Tạo file `customers.txt` ở thư mục gốc, mỗi dòng một mã khách hàng (ví dụ `ABC123`, `XY456`), để ưu tiên khớp mã khách đọc được với danh sách. Không có file thì mã khách lấy trực tiếp từ OCR.

Kết quả nằm trong `output/`:

- `waybills.json`, `waybills.csv`: kết quả trích xuất của từng ảnh
- `<tên ảnh>_ocr_res_img.jpg`: ảnh có vẽ khung các dòng chữ OCR nhận được
- `<tên ảnh>_preprocessed_img.jpg`: ảnh sau bước xoay hướng tài liệu

| Trường | Ý nghĩa |
|---|---|
| `file` | Tên file ảnh |
| `carrier` | Hãng vận chuyển (中通, 圆通, 韵达, 顺丰, 京东, EMS, ...) |
| `tracking_number` | Mã vận đơn |
| `tracking_source` | Nguồn của mã vận đơn: `barcode`, `qrcode` hoặc `ocr` (độ tin cậy giảm dần) |
| `master_tracking_number` | Mã vận đơn mẹ (母单号), hoặc mã vận đơn in trên nhãn khi barcode là mã kiện (mã vận đơn + số thứ tự kiện, ví dụ 融辉物流), nếu có |
| `customer_code` | Mã khách hàng |
| `customer_code_source` | Nguồn của mã khách hàng: `customer_list`, `customer_list_number`, `ocr`, `address_line` (không tách được khối người nhận, lấy mã khách trong dòng có địa chỉ) hoặc `longest_number` (không thấy mã khách nào, lấy chuỗi số dài nhất, độ tin cậy thấp) |
| `customer_candidates` | Các ứng viên mã khách hàng, phân tách bằng `\|` |
| `elapsed_seconds` | Thời gian xử lý ảnh (giây) |

Ảnh vận đơn trong `images/` đặt tên theo mẫu `waybill_<hãng>_<số thứ tự>.jpg`. `images/sample_vi.png` tạo lại được bằng `python tools/make_sample.py` (dùng font Arial có sẵn trên macOS).
