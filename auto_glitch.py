#!/usr/bin/env python3
"""
Glitch This 自动处理脚本
功能：对 example/source.png 进行故障艺术处理，
      随机生成 1-10 的故障强度，每次运行都能保存不冲突。
"""

import os
import sys
import random
from datetime import datetime

# 将当前目录加入模块搜索路径，确保能正确导入 glitch_this 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from glitch_this import ImageGlitcher


def main():
    # ===================== 配置参数 =====================
    # 输入图片路径
    input_path = "example/source.png"

    # 检查输入文件是否存在
    if not os.path.exists(input_path):
        print(f"[错误] 找不到输入文件：{input_path}")
        sys.exit(1)

    # ===================== 生成随机强度 =====================
    # 故障强度随机生成 1~10 的整数
    glitch_amount = random.randint(1, 10)

    # 在终端打印当前使用的随机强度值，方便用户知晓
    print("=" * 50)
    print(f"  输入图片   : {input_path}")
    print(f"  随机强度   : {glitch_amount} / 10")
    print(f"  颜色偏移   : 已开启 (-c)")
    print(f"  强制覆盖   : 已开启 (-f)")
    print("=" * 50)

    # ===================== 确定输出文件名 =====================
    # 获取输入文件的目录和基础名称（不含扩展名）
    output_dir = os.path.dirname(input_path) or "."
    base_name = os.path.splitext(os.path.basename(input_path))[0]

    # 使用随机强度值作为文件名的后缀标识，保证每次生成的图片名称不同
    # 例如：source_glitch_7.png
    output_filename = f"{base_name}_glitch_{glitch_amount}.png"
    output_path = os.path.join(output_dir, output_filename)

    # ===================== 强制覆盖检查 (-f 参数) =====================
    # 如果文件已存在，则直接删除，模拟命令行 -f 参数的强制覆盖行为
    if os.path.exists(output_path):
        print(f"[提示] 文件已存在，将强制覆盖：{output_path}")
        os.remove(output_path)

    # ===================== 执行 Glitch 处理 =====================
    # 创建 ImageGlitcher 实例
    glitcher = ImageGlitcher()

    try:
        # 调用 glitch_image 方法处理图片
        # 第二个参数：故障强度（1~10）
        # color_shift=True：开启颜色偏移效果（对应命令行 -c 参数）
        glitch_img = glitcher.glitch_image(
            input_path,
            glitch_amount,
            color_shift=True  # -c 参数：颜色偏移
        )
    except TypeError:
        # 兼容旧版本：部分版本的 glitch_image 不支持 color_shift 参数
        print("[提示] 当前版本不支持 color_shift 参数，使用默认模式")
        glitch_img = glitcher.glitch_image(
            input_path,
            glitch_amount
        )

    # ===================== 保存图片 =====================
    # 将处理后的图片保存到指定路径
    glitch_img.save(output_path)
    print(f"[保存] 输出文件：{output_path}")

    # ===================== 完成提示 =====================
    print("-" * 50)
    print("[完成] Glitch 处理已结束！请查看生成的图片。")
    print(f"  文件路径：{os.path.abspath(output_path)}")
    print(f"  使用强度：{glitch_amount}")
    print("-" * 50)


if __name__ == "__main__":
    main()