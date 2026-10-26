# Triển khai DownVideo trên Render

Ứng dụng cần chạy **Docker Web Service**, vì yt-dlp và FFmpeg tạo tiến trình hệ điều hành. Không dùng Static Site. `api.php` và XAMPP không cần trên Render.

## Bản triển khai đầu tiên

`render.yaml` cấu hình bản dùng thử miễn phí: một máy chủ, một tác vụ chạy tại một thời điểm, tệp tối đa 512 MB, dung lượng tạm tối đa 1 GB và lưu trong một giờ. Dữ liệu có thể mất sớm hơn khi Render khởi động lại hoặc triển khai lại dịch vụ. Dịch vụ miễn phí có thể ngủ khi không có truy cập; tác vụ đang chạy có thể bị gián đoạn. Video dài hoặc dung lượng lớn có thể cần cấu hình trả phí.

`render.persistent.yaml` là bản tùy chọn trả phí với RAM 2 GB, hai tác vụ đồng thời và ổ lưu trữ 10 GB. Không áp dụng cấu hình trả phí trước khi kiểm tra giá và đồng ý chi phí trên Render.

Free là tên gói máy chủ; băng thông gửi ra và thời gian build vẫn chịu hạn mức của tài khoản. Nếu tài khoản đã có phương thức thanh toán, phần vượt hạn mức có thể được Render tính phí. Kiểm tra giới hạn chi tiêu/băng thông trong Dashboard trước khi dùng để tải các video lớn.

Đây là **website cá nhân có mật khẩu truy cập**. Các thiết bị đăng nhập cùng tài khoản thấy chung hàng đợi và lịch sử. Không bỏ cơ chế đăng nhập để mở cho khách ẩn danh: phiên bản nhiều người dùng cần bổ sung tách quyền sở hữu tác vụ/tệp và kiểm soát lưu lượng mạng.

## Đưa mã nguồn lên GitHub

1. Dùng một repository riêng cho dự án, nên để private. Không dùng repository khác khi chưa kiểm tra nội dung của nó.
2. Đưa mã nguồn và cấu hình ở thư mục dự án lên repository. **Không đưa** `.runtime/`, `.data/`, `downloads/`, `.qa/`, `.env` hoặc mật khẩu lên GitHub; `.gitignore` đã loại các mục này.
3. Kết nối repository đó với tài khoản Render. Bản nén mã nguồn sạch, nếu được cung cấp cùng dự án, cũng không chứa video tải về hay dữ liệu tác vụ.

## Deploy

1. Trong Render, chọn **New → Blueprint**, kết nối repository DownVideo và chọn `render.yaml`.
2. Kiểm tra service là **Docker / Free**, không có persistent disk, rồi áp dụng Blueprint.
3. Render cài các gói Linux, FFmpeg và Deno trong quá trình build. `PORT` do môi trường cung cấp; API health check là `/healthz`.
4. Sau khi deploy thành công, mở **URL HTTPS được Render trả về**. Tên người dùng mặc định là `owner`.
5. Mật khẩu được Render tự tạo trong biến môi trường `DOWNVIDEO_ACCESS_PASSWORD`. Xem trực tiếp trong Dashboard của bạn và dùng tại hộp đăng nhập của trình duyệt. Không gửi mật khẩu vào chat và không commit vào Git.
6. Dán một link video mẫu được phép tải, bấm Phân tích → Tải video → Lưu về máy để xác nhận đường tải trên kết nối của máy chủ.

Không sử dụng URL dự đoán làm bằng chứng đã deploy. Chỉ coi triển khai hoàn tất khi Render báo live và kiểm tra HTTPS/API thành công.

## Biến môi trường

| Biến | Ý nghĩa |
| --- | --- |
| `DOWNVIDEO_PUBLIC=1` | Chạy bản Internet, bắt buộc mật khẩu mạnh |
| `RENDER_EXTERNAL_URL` | Render cung cấp tự động, dùng kiểm tra domain và Origin |
| `DOWNVIDEO_PUBLIC_ORIGIN` | Ghi đè khi dùng domain riêng, ví dụ `https://video.example.com` |
| `DOWNVIDEO_ACCESS_USER` | Tên đăng nhập; mặc định `owner` |
| `DOWNVIDEO_ACCESS_PASSWORD` | Mật khẩu ngẫu nhiên từ 20 ký tự, bắt buộc |
| `DOWNVIDEO_DATA_ROOT` | Thư mục dữ liệu; dùng `/tmp/downvideo` cho Free hoặc `/var/data` khi gắn disk |
| `DOWNVIDEO_MAX_ACTIVE` | Giới hạn tác vụ đồng thời |
| `DOWNVIDEO_MAX_QUEUE` | Giới hạn tổng tác vụ đang chạy/chờ |
| `DOWNVIDEO_MAX_FILE_MB` | Giới hạn một luồng/tệp tải; tệp ghép có thể lớn hơn từng luồng |
| `DOWNVIDEO_MAX_STORAGE_MB` | Ngưỡng kiểm tra dung lượng video tạm |
| `DOWNVIDEO_RETENTION_HOURS` | Thời gian giữ tệp/lịch sử; áp dụng sau tác vụ kết thúc |
| `DOWNVIDEO_MAX_JOB_SECONDS` | Thời gian chạy tối đa của một tác vụ |

Token thao tác chỉ được cấp sau khi đăng nhập. Các đường dẫn video, lịch sử và tài nguyên giao diện đều yêu cầu đăng nhập; `/healthz` chỉ trả trạng thái, không chứa token hay đường dẫn tệp.

## Lưu lâu hơn và domain riêng

Để giữ dữ liệu qua lần khởi động lại, chuyển sang service trả phí và gắn persistent disk tại `/var/data`, đặt `DOWNVIDEO_DATA_ROOT=/var/data`. Docker image chạy ứng dụng bằng UID/GID `10001`; cần xác minh quyền ghi của thư mục được mount ở lần deploy thực tế. Chỉ một instance được sử dụng thư mục dữ liệu này. Không chạy nhiều replica trên cùng bộ tác vụ JSON.

Khi thêm domain riêng, trỏ domain trong Render rồi đặt `DOWNVIDEO_PUBLIC_ORIGIN` bằng origin HTTPS chính xác. Chỉ truy cập ứng dụng qua domain đã cấu hình để việc kiểm tra Host/Origin khớp nhau.

## Kiểm tra trước khi đưa lên Render

```powershell
python -m unittest -v test_backend.py test_deployment.py
python -m py_compile server.py downloader.py deployment.py
```

Kiểm tra HTTP cục bộ bao gồm đăng nhập, token, Host/Origin, health check, cổng `PORT` và dữ liệu tách khỏi mã nguồn. Máy hiện tại không có Docker, nên chưa build/chạy image Linux tại đây. Phần build Linux và tải video từ địa chỉ IP của Render cần được xác nhận sau khi kết nối và deploy.

Nếu có Docker ở máy khác, kiểm tra image bằng `docker build -t downvideo .`. `compose.yaml`, `Caddyfile` và `.env.example` là phương án phụ cho VPS với HTTPS do Caddy quản lý.

Nguồn chính thức: [Render Web Services](https://render.com/docs/web-services), [Docker](https://render.com/docs/docker), [Blueprint](https://render.com/docs/blueprint-spec), [Free](https://render.com/docs/free), [Persistent Disks](https://render.com/docs/disks).

