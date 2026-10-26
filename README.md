# DownVideo

Website tải video có giao diện tiếng Việt, chạy cục bộ trên Windows/XAMPP. Backend Python sử dụng **yt-dlp + FFmpeg + Deno**, tải tệp thật và lưu lịch sử trên máy.

**Đưa lên Internet:** xem [DEPLOY.md](DEPLOY.md). Đã bổ sung cấu hình Docker/Render, mật khẩu truy cập cho bản cá nhân, thư mục dữ liệu riêng và giới hạn tài nguyên. Đây là cấu hình chuẩn bị triển khai, chưa phải xác nhận website đã live.

## Chạy website

1. Cài Python **3.10 trở lên, bản 64-bit** và chọn thêm Python vào PATH.
2. Mở **`start.bat`** trong thư mục dự án. Lần đầu cần Internet để cài thư viện vào `.runtime/` và tải Deno chính thức có kiểm tra SHA-256.
3. Truy cập **http://127.0.0.1:8765**. Giữ cửa sổ máy chủ mở trong lúc sử dụng.

Không cần Node.js, npm, tài khoản hoặc API key. Thư viện được cài riêng vào dự án, không cài vào thư viện Python toàn hệ thống.

Nếu dùng XAMPP, bật Apache, chạy `start.bat`, sau đó mở **http://localhost/DownVideo/**. `api.php` chuyển tiếp yêu cầu tới backend tại cổng 8765. Có thể sử dụng cổng 8765 trực tiếp mà không cần bật Apache.

## Sử dụng

- Dán một hoặc nhiều link, mỗi link một dòng; có thể nhập hoặc kéo thả tệp `.txt`. Mỗi lượt thêm tối đa 100 link.
- Chọn **Phân tích liên kết** để xem thông tin và định dạng thực tế từ nguồn.
- Chọn chất lượng riêng cho từng video hoặc dùng các giới hạn độ phân giải/fps phía trên.
- Bấm **Tải video** hoặc **Tải tất cả**. Backend chạy tối đa 3 tác vụ, các tác vụ còn lại chờ và tự chạy, kể cả khi tải lại trang.
- Bấm **Lưu về máy** khi hoàn tất. Tệp gốc được giữ trong `downloads/<mã-tác-vụ>/`.
- Có thể hủy, thử lại, tìm kiếm lịch sử và ẩn mục đã xử lý. **Ẩn khỏi danh sách không xóa tệp video trên ổ đĩa.**

## Chất lượng và nguồn hỗ trợ

**4K/120fps chỉ tải được khi nguồn cung cấp đúng chất lượng đó.** Website không nâng độ phân giải hay nội suy fps. Các giới hạn phía trên là mức tối đa: nếu nguồn chỉ có 720p/30fps, tệp tải vẫn là 720p/30fps. Chọn một định dạng cụ thể ở hàng video sẽ ưu tiên định dạng đó thay cho giới hạn chung.

Video được giữ nguyên codec, ghép hình/âm thanh hoặc đổi vỏ MP4/MKV bằng FFmpeg, không chủ động nén lại. Lựa chọn Gốc có thể xuất MKV khi cần ghép các codec khác nhau. MP3 là chuyển đổi âm thanh ở 192 kbps.

yt-dlp hỗ trợ nhiều nguồn như YouTube, TikTok, Facebook, Instagram, X/Twitter, Vimeo và link MP4 trực tiếp. **Không có công cụ nào đảm bảo tải mọi link trên Internet**: nguồn có thể yêu cầu đăng nhập, chặn bot, giới hạn khu vực, thay đổi cách phát hoặc bảo vệ bằng DRM. Bản này không nhập cookie, không xử lý đăng nhập, không vượt DRM và không ghi luồng đang phát trực tiếp. Mỗi link là một video; playlist cần tách thành các link video riêng.

Tài liệu chính thức: [yt-dlp](https://github.com/yt-dlp/yt-dlp), [nguồn được hỗ trợ](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), [Deno cho YouTube](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

Chỉ tải nội dung bạn sở hữu hoặc có quyền tải.

## Các tệp chính

| Tệp | Vai trò |
| --- | --- |
| `index.html`, `styles.css`, `app.js` | Giao diện responsive, nhập link, hàng đợi, lịch sử và hướng dẫn |
| `server.py` | HTTP API cục bộ, lập lịch, kiểm tra đầu vào và phục vụ tệp có HTTP Range |
| `downloader.py` | Tiến trình riêng để đọc nguồn, chọn định dạng, tải và xử lý FFmpeg |
| `api.php` | Cầu nối XAMPP đến Python |
| `setup.py`, `requirements.txt` | Cài thư viện trong dự án và Deno |
| `.data/` | Trạng thái tác vụ và cache; không đưa vào Git |
| `downloads/` | Các tệp video/âm thanh hoàn tất; không đưa vào Git |

Backend chỉ lắng nghe `127.0.0.1`, kiểm tra Host, Origin và token cho các thao tác ghi. Đường dẫn nội bộ không được phục vụ bởi máy chủ Python; `.htaccess` bảo vệ các thư mục dữ liệu khi chạy Apache. Không đưa nguyên bản máy chủ phát triển này lên Internet; bản public cần backend được triển khai riêng với xác thực, giới hạn tài nguyên và chính sách lưu trữ.

## Kiểm tra

```powershell
python -m unittest -v test_backend.py
python -m py_compile server.py downloader.py setup.py
C:\xampp\php\php.exe -l api.php
```

Kiểm tra tích hợp nằm trong `.qa/smoke.py` (tệp hỗ trợ cục bộ, không đưa vào Git). Nó kiểm tra tải mẫu MP4 công khai, chuyển MP3, tải từng phần, token và cầu nối PHP. Cần backend ở cổng 8765 và máy chủ PHP ở cổng 8780:

```powershell
C:\xampp\php\php.exe -S 127.0.0.1:8780 -t .
python .qa/smoke.py
```

Để cập nhật khi các nền tảng thay đổi:

```powershell
python -m pip install --upgrade --target .runtime/packages -r requirements.txt
```

Khởi động lại backend sau khi cập nhật. Nếu cổng 8765 đang được dùng, đóng phiên DownVideo cũ trước khi chạy lại.

## Kết quả kiểm tra tại máy hiện tại

- 9 kiểm tra tự động đạt, gồm chọn 4K/120fps khi định dạng đó có sẵn, giới hạn fps, không tạo chất lượng giả, loại DRM và kiểm tra URL.
- Tải thật MP4 mẫu công khai, chuyển MP3, lưu tệp với HTTP Range và cầu nối PHP đều đạt.
- Hàng đợi 7 tác vụ, giới hạn 3 tiến trình, hủy tác vụ chờ và báo lỗi nguồn không có video đều đạt.
- Link YouTube mẫu thử trong phiên này bị nguồn từ chối truy cập; chưa xác nhận tải YouTube thành công tại kết nối hiện tại.
- Chưa xác minh giao diện bằng trình duyệt: công cụ Computer Use tự dừng vì không xác định được URL trên Windows. Đã kiểm tra cú pháp JavaScript/Python/PHP.

