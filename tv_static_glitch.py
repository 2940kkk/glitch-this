#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TV Static Glitch Pro —— 极端老电视故障效果生成器（RGBA 兼容版）
"""

import os
import sys
import random
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image, ImageDraw

try:
    from glitch_this import ImageGlitcher
except ImportError:
    print("[错误] 未找到 glitch_this 库，请确认其存在于当前目录或已 pip 安装。")
    sys.exit(1)


# =========================================================
# 命令行参数
# =========================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="生成带雪花/CRT/撕裂/信号丢失的极端故障图片"
    )
    parser.add_argument("input_path", type=str, help="输入图片路径")
    parser.add_argument("glitch_amount", type=int, nargs="?", default=8,
                        help="glitch 故障强度 1~10")
    parser.add_argument("-r", "--random", action="store_true",
                        help="随机生成 1~10 的故障强度")
    parser.add_argument("-c", "--color-shift", action="store_true",
                        help="开启颜色偏移")
    parser.add_argument("-s", "--static", dest="static_on", action="store_true",
                        default=True, help="开启 TV 雪花噪点（默认开）")
    parser.add_argument("--no-static", dest="static_on", action="store_false")
    parser.add_argument("-n", "--noise", type=float, default=0.3,
                        help="雪花不透明度 0~1")

    parser.add_argument("--scanline", dest="scanline_on", action="store_true",
                        default=True, help="开启 CRT 扫描线")
    parser.add_argument("--no-scanline", dest="scanline_on", action="store_false")
    parser.add_argument("--scan-step", type=int, default=3,
                        help="扫描线间隔像素")

    parser.add_argument("--tear", dest="tear_on", action="store_true",
                        default=True, help="开启画面撕裂抖动")
    parser.add_argument("--no-tear", dest="tear_on", action="store_false")
    parser.add_argument("--tear-count", type=int, default=6)
    parser.add_argument("--tear-shift", type=int, default=40)

    parser.add_argument("--signal-loss", dest="signal_on", action="store_true",
                        default=True, help="开启模拟信号丢失条纹")
    parser.add_argument("--no-signal-loss", dest="signal_on", action="store_false")
    parser.add_argument("--signal-count", type=int, default=2)

    parser.add_argument("-o", "--output", type=str, default=None)
    parser.add_argument("-f", "--force", action="store_true")
    return parser.parse_args()


# =========================================================
# ✅ 改动 1：生成故障图后立刻统一为 RGB，消除 RGBA 通道差异
# =========================================================
def generate_glitch_image(glitcher, input_path, amount, color_shift):
    try:
        img = glitcher.glitch_image(input_path, amount, color_shift=color_shift)
    except TypeError:
        img = glitcher.glitch_image(input_path, amount)
    # 关键：无论原图是 RGBA/P/LA，统一转为 RGB（3 通道）
    return img.convert("RGB")


# =========================================================
# 特效 2：TV 雪花噪点
# =========================================================
def generate_static_noise(size):
    width, height = size
    choices = [0, 85, 170, 255]
    arr = np.random.choice(choices, size=(height, width, 3)).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def overlay_noise(base_img, alpha):
    # 防御：再次确保 base 是 RGB
    base_rgb = base_img.convert("RGB")
    noise_img = generate_static_noise(base_rgb.size)
    return Image.blend(base_rgb, noise_img, alpha=alpha)


# =========================================================
# 特效 3：CRT 扫描线
# =========================================================
def add_crt_scanlines(img, step=3, line_alpha=0.35):
    # 防御：入口转 RGB，避免外部传 RGBA 进来
    base = img.convert("RGB")
    width, height = base.size

    # 用 RGBA 中间层叠加半透明黑线
    base_rgba = base.convert("RGBA")
    overlay = Image.new("RGBA", base_rgba.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    line_color = (0, 0, 0, int(255 * line_alpha))
    for y in range(0, height, step):
        draw.line([(0, y), (width, y)], fill=line_color, width=1)

    base_rgba.alpha_composite(overlay)
    # 最终再转回 RGB，保持通道一致
    return base_rgba.convert("RGB")


# =========================================================
# 特效 4：画面撕裂抖动
# =========================================================
def add_horizontal_tear(img, tear_count=6, max_shift=40):
    # 防御：确保是 3 通道 RGB，否则 np.roll 后赋值会因通道数不同而报错
    img = img.convert("RGB")
    arr = np.array(img)
    height, width, _ = arr.shape

    for _ in range(tear_count):
        band_h = random.randint(int(height * 0.02), int(height * 0.10))
        y_start = random.randint(0, max(0, height - band_h))
        y_end = y_start + band_h
        shift = random.randint(1, max_shift) * random.choice([-1, 1])
        arr[y_start:y_end] = np.roll(arr[y_start:y_end], shift, axis=1)

        tear_line = arr[y_start]
        ch = random.randint(0, 2)
        tear_line[:, ch] = np.clip(tear_line[:, ch].astype(int)
                                   + random.randint(40, 120), 0, 255)

    return Image.fromarray(arr, mode="RGB")


# =========================================================
# 特效 5：模拟信号丢失条纹
# =========================================================
def add_signal_loss(img, signal_count=2):
    # 防御：这里就是报错的直接源头——原图若为 RGBA 4 通道，
    # 把 3 通道 noise 赋给 arr[y:y+2] 会 broadcast 失败
    img = img.convert("RGB")
    arr = np.array(img)
    height, width, channels = arr.shape  # channels 一定是 3

    for _ in range(signal_count):
        band_h = random.randint(int(height * 0.03), int(height * 0.08))
        y_start = random.randint(0, max(0, height - band_h - 2))
        y_end = y_start + band_h

        arr[y_start:y_end] = 0
        if y_end < height:
            # 显式生成与 arr.shape[2] 一致通道数的 noise，彻底保险
            noise = np.random.choice([0, 128, 255],
                                     size=(2, width, channels)).astype(np.uint8)
            arr[y_end:y_end + 2] = noise

    return Image.fromarray(arr, mode="RGB")


# =========================================================
# 输出路径
# =========================================================
def resolve_output_path(args, base_name):
    output_dir = os.path.dirname(args.input_path) or "."
    prefix = args.output if args.output else base_name
    filename = f"{prefix}_tv_{args.glitch_amount}.png"
    output_path = os.path.join(output_dir, filename)

    if os.path.exists(output_path):
        if args.force:
            os.remove(output_path)
            print(f"[提示] -f 启用，覆盖：{output_path}")
        else:
            print(f"[错误] 文件已存在：{output_path}，请加 -f 或换 -o")
            sys.exit(1)
    return output_path


# =========================================================
# 主流程
# =========================================================
def main():
    args = parse_args()

    if not os.path.exists(args.input_path):
        print(f"[错误] 找不到输入文件：{args.input_path}")
        sys.exit(1)
    if args.random:
        args.glitch_amount = random.randint(1, 10)
    if not (1 <= args.glitch_amount <= 10):
        print("[错误] 故障强度必须在 1~10 之间。")
        sys.exit(1)
    if not (0.0 <= args.noise <= 1.0):
        print("[错误] 雪花不透明度必须在 0~1 之间。")
        sys.exit(1)

    print("=" * 60)
    print("  TV Static Glitch Pro 参数")
    print("-" * 60)
    print(f"  输入图片      : {args.input_path}")
    print(f"  故障强度      : {args.glitch_amount}/10")
    print(f"  颜色偏移 (-c) : {'开' if args.color_shift else '关'}")
    print(f"  雪花噪点      : {'开' if args.static_on else '关'}  {args.noise * 100:.0f}%")
    print(f"  CRT 扫描线    : {'开' if args.scanline_on else '关'}  间隔 {args.scan_step}px")
    print(f"  画面撕裂      : {'开' if args.tear_on else '关'}  {args.tear_count} 条 / {args.tear_shift}px")
    print(f"  信号丢失条纹  : {'开' if args.signal_on else '关'}  {args.signal_count} 条")
    print(f"  强制覆盖 (-f) : {'开' if args.force else '关'}")
    print("=" * 60)

    # ---------- 步骤 1：glitch 故障 ----------
    print("[1/5] 生成 glitch 故障图...")
    glitcher = ImageGlitcher()
    img = generate_glitch_image(
        glitcher, args.input_path, args.glitch_amount, args.color_shift
    )

    # ✅ 改动 2：再补一刀 convert，确保后续所有特效看到的都是 RGB
    img = img.convert("RGB")

    # ---------- 步骤 2：信号丢失条纹 ----------
    if args.signal_on:
        print("[2/5] 添加模拟信号丢失条纹...")
        img = add_signal_loss(img, args.signal_count)
    else:
        print("[2/5] 跳过信号丢失条纹")

    # ---------- 步骤 3：画面撕裂 ----------
    if args.tear_on:
        print("[3/5] 添加画面撕裂抖动...")
        img = add_horizontal_tear(img, args.tear_count, args.tear_shift)
    else:
        print("[3/5] 跳过画面撕裂")

    # ---------- 步骤 4：雪花噪点 ----------
    if args.static_on:
        print("[4/5] 叠加 TV 雪花噪点...")
        img = overlay_noise(img, args.noise)
    else:
        print("[4/5] 跳过雪花噪点")

    # ---------- 步骤 5：CRT 扫描线 ----------
    if args.scanline_on:
        print("[5/5] 叠加 CRT 扫描线...")
        img = add_crt_scanlines(img, args.scan_step)
    else:
        print("[5/5] 跳过 CRT 扫描线")

    # ---------- 保存 ----------
    base_name = os.path.splitext(os.path.basename(args.input_path))[0]
    output_path = resolve_output_path(args, base_name)
    img.save(output_path)

    print("-" * 60)
    print("[完成] 已生成带全套电视故障效果的图片！")
    print(f"  文件路径 : {os.path.abspath(output_path)}")
    print(f"  故障强度 : {args.glitch_amount}/10")
    print("-" * 60)


if __name__ == "__main__":
    main()