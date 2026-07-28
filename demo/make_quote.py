import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).parent / "font"
FONT_RELEASE = "https://github.com/orioncactus/pretendard/releases/download/v1.3.9/Pretendard-1.3.9.zip"
FONT_MEMBERS = {
    "public/static/Pretendard-Regular.otf": "Pretendard-Regular.otf",
    "public/static/Pretendard-Bold.otf": "Pretendard-Bold.otf",
}


def ensure_font() -> tuple[str, str]:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [d for d in FONT_MEMBERS.values() if not (FONT_DIR / d).exists()]
    if missing:
        print(f"Pretendard 내려받는 중… ({', '.join(missing)})", file=sys.stderr)
        with urllib.request.urlopen(FONT_RELEASE, timeout=180) as response:
            archive = zipfile.ZipFile(io.BytesIO(response.read()))
        for member, name in FONT_MEMBERS.items():
            (FONT_DIR / name).write_bytes(archive.read(member))
    return str(FONT_DIR / "Pretendard-Regular.otf"), str(FONT_DIR / "Pretendard-Bold.otf")


def render(args: argparse.Namespace) -> Path:
    regular, bold = ensure_font()
    total = args.unit_price * args.quantity

    image = Image.new("RGB", (1240, 900), "white")
    draw = ImageDraw.Draw(image)
    h1 = ImageFont.truetype(bold, 52)
    h2 = ImageFont.truetype(bold, 27)
    body = ImageFont.truetype(regular, 25)
    small = ImageFont.truetype(regular, 22)

    draw.text((80, 60), "견 적 서", font=h1, fill="black")
    draw.text((80, 142), args.vendor, font=h2, fill="black")
    draw.text((80, 183), f"사업자등록번호 {args.biz_no}  |  {args.contact}", font=small, fill="#555")
    draw.line((80, 236, 1160, 236), fill="black", width=3)

    draw.text((80, 262), f"캠페인 : {args.campaign}", font=body, fill="black")
    draw.text((80, 302), "결제수단 : Solana USDC", font=body, fill="black")
    draw.text((80, 342), f"견적일 : {args.date}", font=body, fill="black")

    draw.line((80, 396, 1160, 396), fill="#999", width=2)
    draw.text((80, 412), "품목", font=h2, fill="black")
    draw.text((620, 412), "단가(USDC)", font=h2, fill="black")
    draw.text((880, 412), "수량", font=h2, fill="black")
    draw.text((1000, 412), "금액(USDC)", font=h2, fill="black")
    draw.line((80, 458, 1160, 458), fill="#999", width=2)

    draw.text((80, 482), args.item, font=body, fill="black")
    draw.text((620, 482), f"{args.unit_price:,}", font=body, fill="black")
    draw.text((880, 482), str(args.quantity), font=body, fill="black")
    draw.text((1000, 482), f"{total:,}", font=body, fill="black")

    draw.line((80, 546, 1160, 546), fill="#999", width=2)
    draw.text((620, 572), "합계", font=h2, fill="black")
    draw.text((880, 572), f"{total:,} USDC", font=h2, fill="black")
    draw.line((80, 630, 1160, 630), fill="black", width=3)

    draw.text((80, 664), f"유효기한 : {args.valid_until}", font=small, fill="#555")
    draw.text((80, 704), f"대금수령 지갑 : {args.wallet}", font=small, fill="#555")
    draw.text((80, 744), "※ 본 견적서는 부가세 별도이며, 집행 확정 후 취소가 불가합니다.", font=small, fill="#555")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, "PDF", resolution=150.0)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="데모용 한글 견적서 PDF 생성")
    parser.add_argument("out")
    parser.add_argument("--unit-price", type=int, required=True, help="단가 (USDC 표기)")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--wallet", required=True, help="견적서에 인쇄할 대금수령 지갑")
    parser.add_argument("--vendor", default="OO광고기획")
    parser.add_argument("--item", default="지하철 원패광고 2주")
    parser.add_argument("--campaign", default="아이돌 OO 생일 지하철 광고")
    parser.add_argument("--biz-no", default="123-45-67890")
    parser.add_argument("--contact", default="vendor@example.com")
    parser.add_argument("--date", default="2026-07-28")
    parser.add_argument("--valid-until", default="2026-08-20")
    args = parser.parse_args()

    out = render(args)
    print(f"{out}  단가={args.unit_price:,} 수량={args.quantity} 합계={args.unit_price * args.quantity:,} USDC")


if __name__ == "__main__":
    main()
