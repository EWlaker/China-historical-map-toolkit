# -*- coding: utf-8 -*-
"""
assemble_by_layout.py — 按拼图工作台导出的布局，把图幅拼成整幅

布局 JSON 由 make_puzzle.py 生成的工作台导出，长这样：

    {
      "version": 1,
      "grid": {"cols": 3, "rows": 5},
      "count": 14,
      "items": [
        {"name": "F_004028_xxx_inner.png", "label": "F_004028_xxx",
         "col": 0, "row": 0},
        ...
      ]
    }

本脚本按 (row, col) 把裁切成果摆到网格上拼成一张整图。
**它不涉及地理坐标** —— 输出的是一张"看起来连在一起"的大图，
用于展示、出版、进一步人工处理。要真实坐标请走配准那条路。

用法
----
    python scripts/tools/assemble_by_layout.py puzzle_layout.json
    python scripts/tools/assemble_by_layout.py puzzle_layout.json -s 0.5
    python scripts/tools/assemble_by_layout.py puzzle_layout.json --jpg
    python scripts/tools/assemble_by_layout.py puzzle_layout.json --report
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

# 拼图界面是 3:1 的块，但真实图幅比例不同，所以按**每格自适应**摆放：
# 同一列取该列最大宽度、同一行取该行最大高度，格子对齐但不强拉变形。
Image.MAX_IMAGE_PIXELS = None


def load_layout(path):
    with open(path, encoding="utf-8") as f:
        L = json.load(f)
    if "items" not in L or not L["items"]:
        sys.exit("布局文件里没有 items: %s" % path)
    return L


def main():
    ap = argparse.ArgumentParser(description="按拼图布局把图幅拼成整幅")
    ap.add_argument("layout", help="拼图工作台导出的 puzzle_layout.json")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-s", "--scale", type=float, default=1.0,
                    help="输出缩放系数(默认 1.0 原尺寸)")
    ap.add_argument("-o", "--out", default=None, help="输出文件路径")
    ap.add_argument("--jpg", action="store_true",
                    help="输出 JPEG（默认 PNG；JPEG 小很多但灰度图会有轻微伪影）")
    ap.add_argument("--cols-first", action="store_true",
                    help="布局里的 col/row 顺序与预期相反时用这个翻转")
    ap.add_argument("--report", action="store_true",
                    help="额外导出一份 CSV，记录每幅在整图中的像素位置")
    a = ap.parse_args()

    base = os.path.dirname(os.path.abspath(a.config))
    import yaml
    if os.path.exists(a.config):
        cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
        crop_dir = os.path.join(base, cfg["paths"]["crop"])
    else:
        crop_dir = os.path.dirname(os.path.abspath(a.layout))
        print("[!] 没找到 %s，改从布局文件所在目录找图" % a.config)

    L = load_layout(a.layout)
    items = L["items"]
    cols = max(i["col"] for i in items) + 1
    rows = max(i["row"] for i in items) + 1

    print("布局: %d 幅  %d 列 x %d 行" % (len(items), cols, rows))

    # 读入每幅，记录尺寸
    imgs = {}
    missing = []
    for it in items:
        p = os.path.join(crop_dir, it["name"])
        if not os.path.exists(p):
            missing.append(it["name"])
            continue
        im = Image.open(p)
        imgs[it["name"]] = im
    if missing:
        print("[!] 有 %d 幅找不到原图（下面按缺失处理）:" % len(missing))
        for m in missing[:8]:
            print("     " + m)
        if len(missing) > 8:
            print("     ... 其余 %d 个" % (len(missing) - 8))
    if not imgs:
        sys.exit("一幅都没找到，检查 --config 或原图目录")

    # 每列宽 = 该列最大宽；每行高 = 该行最大高
    colw = [0] * cols
    rowh = [0] * rows
    for it in items:
        im = imgs.get(it["name"])
        if im is None:
            continue
        colw[it["col"]] = max(colw[it["col"]], im.width)
        rowh[it["row"]] = max(rowh[it["row"]], im.height)
    # 空格子给个兜底尺寸，避免整列/整行是 0
    default_w = int(np.median([w for w in colw if w] or [2000]))
    default_h = int(np.median([h for h in rowh if h] or [1500]))
    colw = [w if w else default_w for w in colw]
    rowh = [h if h else default_h for h in rowh]

    # 判断是否彩色（任一幅是彩色就整体用 RGB）—— 体积预估和画布都要用它
    is_color = any(im.mode in ("RGB", "RGBA", "P") for im in imgs.values())

    W = sum(colw)
    H = sum(rowh)
    mpx = W * H / 1e6
    print("输出尺寸: %d x %d 像素  (%.0f 百万像素, %s)" % (
        W, H, mpx, "彩色" if is_color else "灰度"))
    # 提前给出体积预期 —— 拼上百幅时很容易做出几个 GB 的 PNG，
    # 看图软件打不开、也传不动，不如先说清楚再动手。
    if a.jpg:
        est = mpx * (0.9 if is_color else 0.35)
    else:
        est = mpx * (4.0 if is_color else 1.5)
    print("  预计文件大小: 约 %.0f MB (%s)" % (est, "JPEG" if a.jpg else "PNG 无损"))
    if mpx > 150:
        print("  [!] 超过 1.5 亿像素。建议加 -s 0.5 缩小，或用 --jpg 输出，")
        print("      否则很多看图软件会打不开。现在按原样继续生成……")

    canvas = Image.new("RGB" if is_color else "L", (W, H),
                       (255, 255, 255) if is_color else 255)

    xoff = [0] * (cols + 1)
    for c in range(cols):
        xoff[c + 1] = xoff[c] + colw[c]
    yoff = [0] * (rows + 1)
    for r in range(rows):
        yoff[r + 1] = yoff[r] + rowh[r]

    placed = 0
    for k, it in enumerate(sorted(items, key=lambda z: (z["row"], z["col"])), 1):
        im = imgs.get(it["name"])
        if im is None:
            continue
        c, r = it["col"], it["row"]
        # 图文对齐到格子左上角；比格子小的留白。不拉伸 —— 变形比留白糟。
        if is_color and im.mode != "RGB":
            im = im.convert("RGB")
        elif not is_color and im.mode != "L":
            im = im.convert("L")
        canvas.paste(im, (xoff[c], yoff[r]))
        placed += 1
        if k % 25 == 0 or k == len(items):
            print("  已摆放 %d/%d" % (k, len(items)))

    if a.scale != 1.0:
        nw, nh = max(1, int(W * a.scale)), max(1, int(H * a.scale))
        print("缩放到 %d x %d" % (nw, nh))
        canvas = canvas.resize((nw, nh), Image.LANCZOS)

    outdir = os.path.join(base, "work", "03_assembly")
    os.makedirs(outdir, exist_ok=True)
    if a.out:
        out = os.path.abspath(a.out)
    else:
        out = os.path.join(outdir, "assembled." + ("jpg" if a.jpg else "png"))

    if a.jpg:
        canvas.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    else:
        canvas.save(out, "PNG", compress_level=1)

    mb = os.path.getsize(out) / 1024 / 1024
    print()
    print("拼好了: %s" % out)
    print("  %d 幅  %dx%d像素  %s  %.1f MB" % (
        placed, canvas.width, canvas.height,
        "彩色" if canvas.mode == "RGB" else "灰度", mb))

    if a.report:
        rep = os.path.splitext(out)[0] + "_layout.csv"
        import csv
        with open(rep, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["row", "col", "x_px", "y_px", "width", "height", "name", "label"])
            for it in sorted(items, key=lambda z: (z["row"], z["col"])):
                im = imgs.get(it["name"])
                w.writerow([it["row"] + 1, it["col"] + 1,
                            xoff[it["col"]], yoff[it["row"]],
                            im.width if im else "", im.height if im else "",
                            it["name"], it.get("label", "")])
        print("  位置清单: %s" % rep)

    print()
    print("提示: 这张图没有地理坐标，是纯图像拼接。")
    print("      若要能进 GIS 叠加分析，需要图号或接图表 —— 见 docs/命名规则与接图表.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
