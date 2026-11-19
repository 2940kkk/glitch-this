#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双图闪烁 GIF 最小测试样例
用法：
  python tests/test_flicker_gif.py
"""

import os
import sys
import tempfile

# 让测试能从项目根目录导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from tv_flicker_gif import (
    build_flicker_gif,
    load_image_frames,
    MAX_SIZE_MB,
    MAX_WIDTH,
)


def make_solid_png(path, color, size=(200, 200)):
    """生成纯色 PNG"""
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    arr[:, :] = color
    Image.fromarray(arr, mode="RGB").save(path)


def make_gif(path, colors, size=(160, 160), duration=80):
    """生成多帧 GIF"""
    frames = []
    for c in colors:
        arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        arr[:, :] = c
        frames.append(Image.fromarray(arr, mode="RGB"))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=duration, loop=0)


def run():
    tmp = tempfile.mkdtemp(prefix="flicker_test_")
    a_png = os.path.join(tmp, "a.png")
    b_png = os.path.join(tmp, "b.png")
    a_gif = os.path.join(tmp, "a.gif")
    b_gif = os.path.join(tmp, "b.gif")
    out = os.path.join(tmp, "out.gif")

    # --- 用例 1：静态 A + 静态 B ---
    make_solid_png(a_png, (255, 0, 0))
    make_solid_png(b_png, (0, 0, 255))
    build_flicker_gif(a_png, b_png, out,
                      total_frames=12, duration_ms=80,
                      snow_intensity=0.2, b_opacity=0.5,
                      flicker_hz=10, force=True, workers=1)

    assert os.path.exists(out), "输出文件不存在"
    size_mb = os.path.getsize(out) / (1024 * 1024)
    assert size_mb <= MAX_SIZE_MB, f"体积超限：{size_mb:.2f}MB"

    with Image.open(out) as im:
        n = getattr(im, "n_frames", 1)
        assert n == 12, f"帧数不对，期望 12，实际 {n}"
        im.seek(0)
        w, h = im.size
        assert w <= MAX_WIDTH, f"宽度超限：{w}"
        dur = im.info.get("duration")
        assert dur == 80, f"delay 未保留，期望 80，实际 {dur}"
        assert im.info.get("loop") in (0, None), "loop 字段异常"

    print("[OK] 用例 1 通过：静态 A + 静态 B")

    # --- 用例 2：GIF A + GIF B（继承 A 的每帧 delay）---
    make_gif(a_gif, [(200, 0, 0), (0, 200, 0), (0, 0, 200)], duration=50)
    make_gif(b_gif, [(255, 255, 0), (0, 255, 255)], duration=100)

    frames, durs, loop, _ = load_image_frames(a_gif)
    assert len(frames) == 3, "A GIF 帧数解析错误"
    assert all(d == 50 for d in durs), "A GIF delay 解析错误"

    build_flicker_gif(a_gif, b_gif, out,
                      total_frames=18,
                      snow_intensity=0.3, b_opacity=0.7,
                      flicker_hz=6, force=True, workers=1)

    with Image.open(out) as im:
        n = getattr(im, "n_frames", 1)
        assert n == 18, f"帧数不对，期望 18，实际 {n}"
        im.seek(0)
        dur = im.info.get("duration")
        assert dur == 50, f"delay 未继承 A 源，期望 50，实际 {dur}"

    print("[OK] 用例 2 通过：GIF A 继承每帧 delay")

    # --- 用例 3：超限帧数应报错（不静默截断）---
    try:
        build_flicker_gif(a_png, b_png, out,
                          total_frames=1000, force=True, workers=1)
    except SystemExit:
        print("[OK] 用例 3 通过：帧数超限正确触发 SystemExit")
    else:
        raise AssertionError("帧数超限应当抛 SystemExit")

    print("-" * 50)
    print("全部测试通过 ✅")


if __name__ == "__main__":
    run()