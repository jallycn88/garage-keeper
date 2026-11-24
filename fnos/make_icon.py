"""生成车库管家应用图标（ICON.PNG 64 / ICON_256.PNG 256 及桌面入口用多尺寸图）。

纯 PIL 绘制，4 倍超采样后下采样，保证 64px 下依然清晰。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024          # 绘制画布
PX = 4            # 超采样倍数
CANVAS = S * PX

TOP = (29, 78, 216)       # #1d4ed8
BOTTOM = (59, 130, 246)   # #3b82f6
WHITE = (255, 255, 255, 255)


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        color = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    return img


def rounded_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def car_mask(size, k):
    """轿车的侧视轮廓：先画多边形，再模糊+阈值化以获得圆润转角。"""
    mask = Image.new("L", (size, size), 0)
    points = [
        (140, 652), (140, 568), (238, 552), (318, 548),
        (430, 400), (636, 400), (748, 548), (846, 556),
        (884, 598), (884, 652),
    ]
    ImageDraw.Draw(mask).polygon([tuple(p * k for p in pt) for pt in points], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(13 * k))
    return mask.point(lambda v: 255 if v > 132 else 0)


def build():
    size = CANVAS
    k = size / S

    def s(*values):
        return [v * k for v in values]

    bg = vertical_gradient(size, TOP, BOTTOM).convert("RGBA")
    bg.putalpha(rounded_mask(size, int(224 * k)))

    car = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    white = Image.new("RGBA", (size, size), WHITE)
    car.paste(white, (0, 0), car_mask(size, k))

    d = ImageDraw.Draw(car, "RGBA")

    # 车窗（梯形，贴合前风挡倾角）
    window = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(window).polygon(
        [tuple(p * k for p in pt) for pt in [(456, 424), (628, 424), (706, 528), (386, 528)]],
        fill=(37, 99, 235, 255),
    )
    window = window.filter(ImageFilter.GaussianBlur(4 * k))
    car = Image.alpha_composite(car, Image.composite(window, Image.new("RGBA", (size, size), (0, 0, 0, 0)), car_mask(size, k)))
    d = ImageDraw.Draw(car, "RGBA")

    # 轮拱与车轮
    for cx in (300, 712):
        d.ellipse(s(cx - 76, 596, cx + 76, 748), fill=(37, 99, 235, 255))
        d.ellipse(s(cx - 50, 622, cx + 50, 722), fill=WHITE)
        d.ellipse(s(cx - 20, 652, cx + 20, 692), fill=(37, 99, 235, 255))

    icon = Image.alpha_composite(bg, car)
    return icon


def main():
    root = Path(__file__).resolve().parent
    pkg = root / "garage-keeper"
    big = build()

    targets = [
        (pkg / "ICON.PNG", 64),
        (pkg / "ICON_256.PNG", 256),
        (pkg / "app" / "ui" / "images" / "icon_64.png", 64),
        (pkg / "app" / "ui" / "images" / "icon_256.png", 256),
    ]
    for path, px in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        big.resize((px, px), Image.LANCZOS).save(path, format="PNG", optimize=True)
        print(f"{path.relative_to(root)}  {px}x{px}  {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
