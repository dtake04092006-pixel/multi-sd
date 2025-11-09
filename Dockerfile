# 1. Chọn một image Python gốc (nên dùng 3.11 như bạn đang dùng)
FROM python:3.11-slim

# 2. Đặt thư mục làm việc bên trong container
WORKDIR /app

# 3. Sao chép file requirements trước để tận dụng cache
COPY requirements.txt .

# 4. Cài đặt tất cả các thư viện
RUN pip install --no-cache-dir -r requirements.txt

# 5. Sao chép toàn bộ code của bạn vào /app
COPY . .

# 6. Mở port 10000 (vì Flask/waitress của bạn chạy ở port đó)
EXPOSE 10000

# 7. Lệnh để chạy script khi container khởi động
CMD ["python", "multisd.py"]
