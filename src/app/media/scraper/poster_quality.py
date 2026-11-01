"""海报质量判定：区分竖版正面封面、占位图与由横版剧照裁出的伪海报."""

from __future__ import annotations

import os

from PIL import Image, ImageChops, ImageStat

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def find_image(target_dir: str, base: str) -> str | None:
    for ext in IMAGE_EXTENSIONS:
        path = os.path.join(target_dir, f"{base}{ext}")
        if os.path.exists(path):
            return path
    return None


def is_placeholder_image(path: str) -> bool:
    """识别 NOW PRINTING 等近灰白占位图."""
    try:
        with Image.open(path) as img:
            sample = img.convert("RGB").resize((64, 64))
            rgb_stat = ImageStat.Stat(sample)
            hsv_stat = ImageStat.Stat(sample.convert("HSV"))
        brightness = hsv_stat.mean[2]
        saturation = hsv_stat.mean[1]
        channel_delta = max(rgb_stat.mean) - min(rgb_stat.mean)
        deviation = sum(rgb_stat.stddev) / 3
        return (saturation < 12 and brightness > 220) or (brightness > 205 and channel_delta < 14 and deviation < 22)
    except Exception:
        return False


def is_bad_poster(path: str) -> bool:
    """横版、占位图或损坏图都不满足竖版海报要求."""
    try:
        with Image.open(path) as img:
            width, height = img.size
        # 147x200/160x227 缩略图不算合格高清海报。
        return width < 300 or width > height * 1.1 or is_placeholder_image(path)
    except Exception:
        return True


def is_fanart_crop(poster_path: str, fanart_path: str) -> bool:
    """判断 poster 是否只是横版 fanart 的 2:3 裁切（上一版伪海报）."""
    try:
        with Image.open(poster_path) as poster_img, Image.open(fanart_path) as fanart_img:
            poster = poster_img.convert("RGB")
            fanart = fanart_img.convert("RGB")
            pw, ph = poster.size
            fw, fh = fanart.size
            # 旧逻辑是原图不缩放直接裁切，所以高度一致；DMM ps 等真竖版不会命中。
            if fw <= fh * 1.15 or abs(ph - fh) > 2:
                return False
            target_w = max(1, int(fh * 2 / 3))
            boxes = (
                (fw - target_w, 0, fw, fh),
                (0, 0, target_w, fh),
                ((fw - target_w) // 2, 0, (fw - target_w) // 2 + target_w, fh),
            )
            for box in boxes:
                crop = fanart.crop(box).resize(poster.size)
                diff = ImageStat.Stat(ImageChops.difference(poster, crop)).mean
                if sum(diff) / 3 < 18:
                    return True
    except Exception:
        return False
    return False


def has_legacy_watermark_marker(target_dir: str) -> bool:
    """旧版 .watermark 是 40 字节配置摘要；新版是 JSON 文件摘要."""
    path = os.path.join(target_dir, ".watermark")
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            raw = handle.read().strip()
    except OSError:
        return False
    return bool(raw) and not raw.startswith("{") and len(raw) <= 64


def synthetic_poster_path(target_dir: str) -> str | None:
    """返回由 fanart/backdrop 裁出的伪 poster 路径；没有则返回 None."""
    poster = find_image(target_dir, "poster")
    if not poster:
        return None
    for base in ("fanart", "backdrop"):
        fanart = find_image(target_dir, base)
        if fanart and is_fanart_crop(poster, fanart):
            return poster
    return None
