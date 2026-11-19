#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TV Flicker GIF —— 双图 / 单图 闪烁 GIF 生成器（技术流增强版 + 交作业救急补丁）
================================================================================
技术流三件套：
  1) --auto-amount   : 依据原图对比度 + 边缘密度，自动推导故障强度
  2) --envelope K    : 故障强度沿时间按曲线变化 none|sine|saw|pulse|decay
  3) --style-ref     : 用参考图对每帧做直方图匹配（朴素风格迁移）
内存保护：
  4) --memory-safe   : M2 8GB 推荐，单进程 + 每帧 gc
交作业救急补丁（本次新增）：
  ✅ 5) 超 10MB 不再删除文件，只警告；保留 --strict-size 旧行为
  ✅ 6) --compress N : 保存前量化到 N 色全局调色板，显著降体积（可省 30%~60%）
  ✅ 7) --max-width  : 临时降低宽度上限（如 320/240），体积影响最大
原有功能完全兼容：双图 / 单图闪烁、480/120/10MB 上限、delay/loop/transparency 保留
"""

import os
import sys
import gc
import random
import tempfile
import argparse
from multiprocessing import Pool, cpu_count

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image, ImageSequence

try:
    from glitch_this import ImageGlitcher
except ImportError:
    print("[错误] 未找到 glitch_this 库，请确认其存在于当前目录或已 pip 安装。")
    sys.exit(1)

try:
    from tv_static_glitch import (
        generate_glitch_image,
        overlay_noise,
        add_signal_loss,
        add_horizontal_tear,
        add_crt_scanlines,
    )
except ImportError:
    print("[错误] 未找到 tv_static_glitch.py，请确认与本脚本同目录。")
    sys.exit(1)


# =========================================================
# 硬上限
# =========================================================
MAX_WIDTH = 480
MAX_FRAMES = 120
MAX_SIZE_MB = 10

# M2 8GB 建议上限；普通机器可覆盖
DEFAULT_WORKERS_MAC8G = 2

# ✅ 补丁：允许合法的颜色档位
VALID_QUANT_COLORS = (16, 32, 64, 128, 192, 256)


# =========================================================
# 参数面板
# =========================================================
def parse_args():
    parser = argparse.ArgumentParser(description="双图 / 单图 闪烁 GIF 生成器（技术流增强版）")

    parser.add_argument("a_path", type=str, help="A 图路径 (PNG/JPG/GIF)")
    parser.add_argument("b_path", type=str, nargs="?", default=None,
                        help="B 图路径；--single 模式可省略")

    # ---- 闪烁核心 ----
    parser.add_argument("--single", action="store_true", help="单图闪烁模式")
    parser.add_argument("--glitch-amount", type=int, default=7,
                        help="闪烁态故障强度 1~10，默认 7")
    parser.add_argument("--flicker-hz", type=float, default=8.0,
                        help="每秒闪烁切换次数，默认 8")
    parser.add_argument("--b-opacity", type=float, default=0.6,
                        help="闪烁态透出比例 0~1")
    parser.add_argument("--snow-intensity", type=float, default=0.3,
                        help="雪花叠加不透明度 0~1")
    parser.add_argument("--total-frames", type=int, default=48,
                        help=f"总帧数，上限 {MAX_FRAMES}")
    parser.add_argument("--duration-ms", type=int, default=60,
                        help="静态源每帧延迟 ms；源为 GIF 时优先继承")
    parser.add_argument("--loop", dest="loop", action="store_true", default=True)
    parser.add_argument("--no-loop", dest="loop", action="store_false")

    # ---- 技术流三件套 ----
    parser.add_argument("--auto-amount", action="store_true",
                        help="自适应故障强度：根据原图对比度 + 边缘密度自动推导 1~10")
    parser.add_argument("--envelope", type=str, default="none",
                        choices=["none", "sine", "saw", "pulse", "decay"],
                        help="故障强度随时间变化的包络曲线，默认 none")
    parser.add_argument("--style-ref", type=str, default=None,
                        help="风格参考图路径，输出每帧对该图做直方图匹配")

    # ---- 8GB 内存友好 ----
    parser.add_argument("--memory-safe", action="store_true",
                        help="强制单进程 + 每帧 gc，M2 8GB 推荐")

    # ✅ 补丁 5/6/7：交作业救急三开关
    parser.add_argument("--strict-size", action="store_true",
                        help="严格模式：超过 10MB 直接删除（旧行为）。默认不加则保留文件仅警告")
    parser.add_argument("--compress", type=int, default=None, metavar="COLORS",
                        help=f"保存前量化到 N 色全局调色板，可选 {VALID_QUANT_COLORS}，显著降体积")
    parser.add_argument("--max-width", type=int, default=None, metavar="PX",
                        help="临时降低宽度上限（如 320/240），对体积影响最大")

    # ---- 辅助 ----
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None,
                        help=f"子进程数，默认 min(cpu,{DEFAULT_WORKERS_MAC8G})；--memory-safe 时强制 1")
    parser.add_argument("-o", "--output", type=str, default=None)
    parser.add_argument("-f", "--force", action="store_true")
    parser.add_argument("--preview", action="store_true")

    return parser.parse_args()


# =========================================================
# 图像加载
# ✅ 补丁 7：load_image_frames 支持 width_cap 注入
# =========================================================
def load_image_frames(path, width_cap=None):
    if not os.path.exists(path):
        print(f"[错误] 找不到输入文件：{path}")
        sys.exit(1)

    cap = width_cap or MAX_WIDTH  # ✅ 默认沿用 MAX_WIDTH

    frames, durations = [], []
    with Image.open(path) as im:
        im.load()
        for frame in ImageSequence.Iterator(im):
            dur = int(frame.info.get("duration", 60)) or 60
            durations.append(dur)
            frames.append(frame.convert("RGB").copy())

        loop = im.info.get("loop", None)
        transparency = frames[0].info.get("transparency") if frames else None

    if frames:
        w, h = frames[0].size
        if w > cap:  # ✅ 用 cap 判断
            new_h = int(h * cap / w)
            print(f"[提示] {os.path.basename(path)} 超过宽度上限 {cap}，缩放到 {cap}x{new_h}")
            frames = [f.resize((cap, new_h), Image.LANCZOS) for f in frames]

    return frames, durations, loop, transparency


def align_b_to_a(a_frames, b_frames):
    if not a_frames or not b_frames:
        return b_frames
    target = a_frames[0].size
    return [f if f.size == target else f.resize(target, Image.LANCZOS) for f in b_frames]


# =========================================================
# 技术流 1：自适应故障强度
# =========================================================
def auto_glitch_amount(frame):
    gray = np.asarray(frame.convert("L"), dtype=np.float32)
    std_score = float(gray.std()) / 64.0
    gx = np.abs(gray[:, 1:] - gray[:, :-1]).mean()
    gy = np.abs(gray[1:, :] - gray[:-1, :]).mean()
    edge_score = (gx + gy) * 0.5 / 32.0
    v = 4 + 3 * min(std_score, 1.0) + 3 * min(edge_score, 1.0)
    return int(max(1, min(10, round(v))))


# =========================================================
# 技术流 2：故障包络曲线
# =========================================================
def make_envelope(kind, total_frames):
    t = np.linspace(0, 1, total_frames, dtype=np.float32)
    if kind == "none" or total_frames <= 0:
        return np.ones(max(1, total_frames), dtype=np.float32)
    if kind == "sine":
        return (0.5 + 0.5 * np.sin(t * 2 * np.pi * 2)).astype(np.float32)
    if kind == "saw":
        return ((t * 4) % 1.0).astype(np.float32)
    if kind == "pulse":
        x = (t % 0.25)
        return np.clip(3.0 * np.exp(-x * 20), 0, 1).astype(np.float32)
    if kind == "decay":
        return np.exp(-t * 3).astype(np.float32)
    return np.ones(total_frames, dtype=np.float32)


# =========================================================
# 技术流 3：直方图匹配（朴素风格迁移）
# =========================================================
def histogram_match(source_img, ref_img):
    src = np.asarray(source_img.convert("RGB"))
    ref = np.asarray(ref_img.convert("RGB").resize(source_img.size, Image.BILINEAR))

    out = np.empty_like(src)
    for ch in range(3):
        s_flat = src[..., ch].ravel()
        r_flat = ref[..., ch].ravel()

        s_hist, _ = np.histogram(s_flat, bins=256, range=(0, 256))
        r_hist, _ = np.histogram(r_flat, bins=256, range=(0, 256))

        s_cdf = np.cumsum(s_hist).astype(np.float64)
        r_cdf = np.cumsum(r_hist).astype(np.float64)
        s_cdf /= s_cdf[-1] + 1e-8
        r_cdf /= r_cdf[-1] + 1e-8

        lut = np.searchsorted(r_cdf, s_cdf).clip(0, 255).astype(np.uint8)
        out[..., ch] = lut[src[..., ch]]

    return Image.fromarray(out, mode="RGB")


# =========================================================
# ✅ 补丁 6：全局调色板量化（独立 helper）
# =========================================================
def quantize_frames_to_palette(frames, colors):
    """
    用第一帧算一个全局调色板，所有帧量化到同一 palette（dither 关闭），
    既保证颜色一致不闪变，又最大化帧间压缩，显著降低体积。
    返回 P 模式帧列表；colors 非法或帧为空则原样返回。
    """
    if not frames or colors not in VALID_QUANT_COLORS:
        return frames

    # 第一帧建立全局调色板（MEDIANCUT 比默认更快且稳定）
    ref_p = frames[0].quantize(colors=colors, method=Image.MEDIANCUT)
    out = [ref_p]
    # 其余帧复用同一 palette，dither=0 关闭抖动（抖动会增加帧间差异）
    for f in frames[1:]:
        out.append(f.quantize(colors=colors, palette=ref_p.palette, dither=0))
    return out


# =========================================================
# 单图模式：生成故障对照帧
# =========================================================
def build_single_variant_frames(a_frames, glitch_amount, auto_amount=False):
    glitcher = ImageGlitcher()
    variant = []

    for i, frame in enumerate(a_frames):
        amount = auto_glitch_amount(frame) if auto_amount else glitch_amount

        tmp_path = os.path.join(tempfile.gettempdir(),
                                f"_flicker_single_{os.getpid()}_{i}.png")
        frame.convert("RGB").save(tmp_path)
        try:
            g = generate_glitch_image(glitcher, tmp_path, amount, color_shift=True)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        g = add_signal_loss(g, signal_count=2)
        g = add_horizontal_tear(g, tear_count=6, max_shift=50)
        variant.append(g.convert("RGB"))

    return variant


# =========================================================
# Worker 侧
# =========================================================
_SNOW_CACHE = 0.3


def render_one_frame(job):
    """job = (a_img, b_img, b_alpha, seed)"""
    a_img, b_img, b_alpha, seed = job
    np.random.seed(seed & 0xFFFFFFFF)
    random.seed(seed)

    base = Image.blend(a_img, b_img, alpha=b_alpha) \
        if (b_img is not None and b_alpha > 0) else a_img.copy()

    return overlay_noise(base, _SNOW_CACHE)


# =========================================================
# 任务调度（含 envelope）
# =========================================================
def build_jobs(a_frames, b_frames, total_frames, flicker_hz,
               per_frame_duration_ms, b_opacity, base_seed, envelope=None):
    n_a, n_b = len(a_frames), len(b_frames)
    if n_a == 0 or n_b == 0:
        print("[错误] A 或 B 帧序列为空。")
        sys.exit(1)

    if per_frame_duration_ms <= 0:
        per_frame_duration_ms = 60
    frames_per_toggle = max(1, round(1000.0 / flicker_hz / per_frame_duration_ms))

    if envelope is None:
        envelope = np.ones(total_frames, dtype=np.float32)

    jobs = []
    for i in range(total_frames):
        a_i = a_frames[i % n_a]

        phase = (i // frames_per_toggle) % 2
        if phase == 1:
            alpha = float(b_opacity) * float(envelope[i])
            b_i = b_frames[i % n_b] if alpha > 0.05 else None
            if b_i is None:
                alpha = 0.0
        else:
            b_i = None
            alpha = 0.0

        seed = (base_seed + i * 7919) & 0xFFFFFFFF
        jobs.append((a_i, b_i, alpha, seed))

    return jobs


# =========================================================
# GIF 保存 / 预览
# ✅ save_gif 已能处理 P 模式（量化后的帧），逻辑不变
# =========================================================
def save_gif(frames, out_path, durations, loop_flag, transparency):
    if not frames:
        print("[错误] 没有可保存的帧。")
        sys.exit(1)

    save_kwargs = {
        "save_all": True,
        "append_images": frames[1:],
        "duration": durations[:len(frames)],
        "loop": 0 if loop_flag else 1,
        "optimize": True,
    }
    if transparency is not None:
        try:
            save_kwargs["transparency"] = int(transparency)
        except (TypeError, ValueError):
            pass

    frames[0].save(out_path, format="GIF", **save_kwargs)


def preview_gif(frames, durations):
    try:
        import tkinter as tk
        from PIL import ImageTk
    except ImportError:
        print("[提示] 未安装 tkinter，跳过预览。")
        return

    root = tk.Tk()
    root.title("TV Flicker GIF 预览")
    # ✅ 量化后是 P 模式，预览前统一转 RGB 以便 ImageTk 显示
    w, h = frames[0].size
    root.geometry(f"{w}x{h}")
    label = tk.Label(root); label.pack()
    state = {"idx": 0, "photos": []}

    def tick():
        i = state["idx"] % len(frames)
        photo = ImageTk.PhotoImage(frames[i].convert("RGB"))
        state["photos"].append(photo)
        label.configure(image=photo)
        state["idx"] += 1
        root.after(durations[i] if i < len(durations) else 60, tick)

    tick()
    root.mainloop()


# =========================================================
# 主入口
# ✅ 补丁签名：新增 strict_size / compress_colors / max_width_override
# =========================================================
def build_flicker_gif(a_path, b_path, output_path, *,
                      single_mode=False,
                      glitch_amount=7,
                      flicker_hz=8.0,
                      b_opacity=0.6,
                      snow_intensity=0.3,
                      total_frames=48,
                      duration_ms=60,
                      loop=True,
                      seed=None,
                      workers=None,
                      force=False,
                      preview=False,
                      auto_amount=False,
                      envelope_kind="none",
                      style_ref_path=None,
                      memory_safe=False,
                      strict_size=False,        # ✅ 补丁 5
                      compress_colors=None,     # ✅ 补丁 6
                      max_width_override=None): # ✅ 补丁 7
    # ---------- 校验 ----------
    if not single_mode and not b_path:
        print("[错误] 未提供 B 图。请使用 B 路径，或 --single。")
        sys.exit(1)
    if not (0.0 <= snow_intensity <= 1.0):
        print("[错误] snow_intensity 必须 0~1。"); sys.exit(1)
    if not (0.0 <= b_opacity <= 1.0):
        print("[错误] b_opacity 必须 0~1。"); sys.exit(1)
    if not auto_amount and not (1 <= glitch_amount <= 10):
        print("[错误] glitch_amount 必须 1~10。"); sys.exit(1)
    if total_frames > MAX_FRAMES:
        print(f"[错误] total_frames={total_frames} 超过上限 {MAX_FRAMES}。")
        sys.exit(1)
    if flicker_hz <= 0:
        print("[错误] flicker_hz 必须 > 0。"); sys.exit(1)
    if style_ref_path and not os.path.exists(style_ref_path):
        print(f"[错误] 找不到 style-ref：{style_ref_path}"); sys.exit(1)
    # ✅ 校验量化档位
    if compress_colors is not None and compress_colors not in VALID_QUANT_COLORS:
        print(f"[错误] --compress 只能是 {VALID_QUANT_COLORS} 之一。"); sys.exit(1)
    # ✅ 校验宽度
    if max_width_override is not None and max_width_override <= 0:
        print("[错误] --max-width 必须 > 0。"); sys.exit(1)

    # ---------- 输出路径 ----------
    if output_path is None:
        base = os.path.splitext(os.path.basename(a_path))[0]
        suffix = "_flicker" if not single_mode else "_flicker_single"
        output_path = os.path.join(os.path.dirname(a_path) or ".",
                                   f"{base}{suffix}.gif")
    if os.path.exists(output_path):
        if force:
            os.remove(output_path)
            print(f"[提示] -f 覆盖：{output_path}")
        else:
            print(f"[错误] 输出存在：{output_path}，请加 -f 或换 -o")
            sys.exit(1)

    # ---------- 1. 加载 A ----------
    print("[1/7] 加载 A 图...")
    a_frames, a_durs, a_loop, a_trans = load_image_frames(a_path, max_width_override)

    # ---------- 2. 生成 B ----------
    if single_mode:
        hint = "自适应" if auto_amount else f"固定强度 {glitch_amount}"
        print(f"[2/7] 单图模式：生成对照故障帧（{hint}）...")
        b_frames = build_single_variant_frames(a_frames, glitch_amount,
                                               auto_amount=auto_amount)
    else:
        print("[2/7] 加载 B 图...")
        b_frames, _, _, _ = load_image_frames(b_path, max_width_override)
    b_frames = align_b_to_a(a_frames, b_frames)

    # ---------- 3. delay / loop ----------
    if len(a_durs) > 1:
        durations = [a_durs[i % len(a_durs)] for i in range(total_frames)]
    else:
        durations = [max(20, duration_ms)] * total_frames
    loop_final = (a_loop == 0) if a_loop is not None else loop

    base_seed = seed if seed is not None else random.randint(0, 2 ** 31 - 1)

    # ---------- 4. 包络曲线 ----------
    envelope = make_envelope(envelope_kind, total_frames)
    print(f"[3/7] 生成 {envelope_kind} 包络曲线（均值 {envelope.mean():.2f}）...")

    # ---------- 5. 渲染（含 8GB 保护） ----------
    global _SNOW_CACHE
    _SNOW_CACHE = snow_intensity

    print(f"[4/7] 构建 {total_frames} 帧任务...")
    jobs = build_jobs(a_frames, b_frames, total_frames, flicker_hz,
                      durations[0], b_opacity, base_seed, envelope)

    if memory_safe:
        n_workers = 1
        print("[5/7] 内存安全模式：单进程渲染 + 每帧 gc...")
    else:
        n_workers = workers or min(cpu_count(), DEFAULT_WORKERS_MAC8G)
        print(f"[5/7] 使用 {n_workers} 个 Worker 渲染...")

    if n_workers <= 1 or total_frames <= 4:
        frames = []
        for j in jobs:
            frames.append(render_one_frame(j))
            if memory_safe:
                gc.collect()
    else:
        with Pool(processes=n_workers) as pool:
            frames = pool.map(render_one_frame, jobs)

    # 渲染完可释放任务表，降低峰值
    del jobs
    gc.collect()

    # ---------- 6. 风格迁移 ----------
    if style_ref_path:
        print(f"[6/7] 应用风格迁移（参考：{os.path.basename(style_ref_path)}）...")
        ref_frames, _, _, _ = load_image_frames(style_ref_path, max_width_override)
        ref_img = ref_frames[0]
        for idx in range(len(frames)):
            frames[idx] = histogram_match(frames[idx], ref_img)
        del ref_frames, ref_img
        gc.collect()
    else:
        print("[6/7] 未启用风格迁移，跳过")

    # ✅ 补丁 6：可选全局调色板量化（保存前、预览后皆可看到真实体积效果）
    if compress_colors is not None:
        print(f"[7/7] 量化到 {compress_colors} 色全局调色板以压缩体积...")
        frames = quantize_frames_to_palette(frames, compress_colors)
        gc.collect()
    else:
        print("[7/7] 未启用调色板量化，跳过")

    # ---------- 预览（先保存再预览？否：先量化→预览→保存，保证预览所见即所得） ----------
    if preview:
        preview_gif(frames, durations)

    # ---------- 保存 ----------
    save_gif(frames, output_path, durations, loop_final, a_trans)

    # ✅ 补丁 5：默认不删除超限文件，只警告；--strict-size 才删
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    if size_mb > MAX_SIZE_MB:
        if strict_size:
            os.remove(output_path)
            print(f"[错误] 体积 {size_mb:.2f}MB 超过 {MAX_SIZE_MB}MB（--strict-size 已启用），已删除。")
            sys.exit(1)
        else:
            print(f"[警告] 体积 {size_mb:.2f}MB 超过软上限 {MAX_SIZE_MB}MB，"
                  f"文件已保留：{os.path.abspath(output_path)}")
            print("       如需瘦身：降 --total-frames / --snow-intensity，"
                  "或加 --compress 128 / --max-width 320。")

    print("-" * 60)
    print(f"[完成] {'单图' if single_mode else '双图'}闪烁 GIF 已生成！")
    print(f"  输出文件 : {os.path.abspath(output_path)}")
    print(f"  帧数/延迟: {total_frames} 帧, ≈{durations[0]} ms")
    print(f"  包络     : {envelope_kind}   风格: {'开' if style_ref_path else '关'}   "
          f"自适应: {'开' if auto_amount else '关'}")
    print(f"  量化     : {compress_colors or '关'}   宽度: {max_width_override or MAX_WIDTH}")
    print(f"  体积     : {size_mb:.2f} MB")
    print("-" * 60)

    return output_path


# =========================================================
# CLI
# =========================================================
def main():
    args = parse_args()

    print("=" * 62)
    print("  TV Flicker GIF 参数（技术流增强版 + 救急补丁）")
    print("-" * 62)
    print(f"  模式         : {'单图闪烁' if args.single else '双图闪烁'}")
    print(f"  A 图         : {args.a_path}")
    if not args.single:
        print(f"  B 图         : {args.b_path}")
    print(f"  故障强度     : {'自适应' if args.auto_amount else f'{args.glitch_amount}/10'}")
    print(f"  包络曲线     : {args.envelope}")
    print(f"  风格参考     : {args.style_ref if args.style_ref else '未启用'}")
    print(f"  闪烁频率     : {args.flicker_hz} Hz")
    print(f"  透出比例     : {args.b_opacity * 100:.0f}%")
    print(f"  雪花强度     : {args.snow_intensity * 100:.0f}%")
    print(f"  总帧数       : {args.total_frames}（上限 {MAX_FRAMES}）")
    print(f"  每帧延迟     : {args.duration_ms} ms")
    print(f"  循环         : {'开' if args.loop else '关'}")
    print(f"  内存安全     : {'开（推荐 M2 8GB）' if args.memory_safe else '关'}")
    print(f"  调色板量化   : {args.compress if args.compress else '关'}")
    print(f"  宽度上限     : {args.max_width if args.max_width else MAX_WIDTH}")
    print(f"  严格体积     : {'开（超限删文件）' if args.strict_size else '关（超限保留+警告）'}")
    print("=" * 62)

    build_flicker_gif(
        args.a_path, args.b_path, args.output,
        single_mode=args.single,
        glitch_amount=args.glitch_amount,
        flicker_hz=args.flicker_hz,
        b_opacity=args.b_opacity,
        snow_intensity=args.snow_intensity,
        total_frames=args.total_frames,
        duration_ms=args.duration_ms,
        loop=args.loop,
        seed=args.seed,
        workers=args.workers,
        force=args.force,
        preview=args.preview,
        auto_amount=args.auto_amount,
        envelope_kind=args.envelope,
        style_ref_path=args.style_ref,
        memory_safe=args.memory_safe,
        strict_size=args.strict_size,        # ✅
        compress_colors=args.compress,       # ✅
        max_width_override=args.max_width,   # ✅
    )


if __name__ == "__main__":
    main()