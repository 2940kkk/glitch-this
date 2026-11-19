import argparse
import os
import sys

# 添加当前目录到系统路径，确保能找到 glitch_this
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from glitch_this import ImageGlitcher
except ImportError:
    print("错误：未找到 glitch_this 库。请确保该库已安装或存在于此目录下。")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="对图片应用 glitch 效果")
    parser.add_argument("input_path", type=str, help="输入图片路径")
    parser.add_argument("num_glitches", type=int, help="要生成的 glitch 图片数量")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="输出文件名的前缀（不指定则默认使用原文件名）")
    parser.add_argument("-f", "--file_format", type=str, default="png",
                        choices=["png", "jpg"], help="输出图片格式 (png 或 jpg)")
    
    args = parser.parse_args()

    # 检查输入文件是否存在
    if not os.path.exists(args.input_path):
        print(f"错误：找不到输入文件 '{args.input_path}'")
        sys.exit(1)

    glitcher = ImageGlitcher()

    # 获取输出目录
    output_dir = os.path.dirname(args.input_path) or "."

    # 确定输出名称前缀
    if args.output:
        prefix = args.output
    else:
        prefix = os.path.splitext(os.path.basename(args.input_path))[0]

    # 循环生成并保存
    for i in range(args.num_glitches):
        print(f"正在生成第 {i+1} 张图片...")
        # 移除了 color_shift=True 参数
        glitch_img = glitcher.glitch_image(args.input_path, 2)
        
        # 使用数字后缀区分每次生成的图片，避免名称重复
        out_filename = f"{prefix}_{i+1}.{args.file_format}"
        out_path = os.path.join(output_dir, out_filename)
        
        glitch_img.save(out_path)
        print(f"已保存: {out_path}")

if __name__ == "__main__":
    main()
