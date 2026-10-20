from PIL import Image, ImageDraw, ImageFont

lines = [
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
    "Độc lập - Tự do - Hạnh phúc",
    "Hóa đơn bán hàng số: 0012345",
    "Khách hàng: Nguyễn Văn Đức",
    "Tổng tiền thanh toán: 1.250.000 đồng",
    "Hello PaddleOCR 2026",
]

font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 36)
img = Image.new("RGB", (1000, 80 + 70 * len(lines)), "white")
draw = ImageDraw.Draw(img)
for i, line in enumerate(lines):
    draw.text((40, 40 + i * 70), line, fill="black", font=font)
img.save("images/sample_vi.png")
