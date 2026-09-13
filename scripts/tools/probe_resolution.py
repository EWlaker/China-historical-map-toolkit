# -*- coding: utf-8 -*-
"""
probe_resolution.py — 探测扫描件的实际尺寸，推荐裁切输出分辨率

解决的问题
----------
`crop.out_size` 该填多少？原来只能靠猜：
填小了浪费扫描精度，填大了白占空间，填错了还会把地图拉变形 —— 而画面
上根本看不出来。

本工具抽样跑一遍「纠斜 -> 找图廓 -> 找内容边界」，统计每幅**裁到内容后
的真实像素尺寸**，据此给出几档可选输出尺寸，并说明各自代价。

它只读不写（除非加 --apply），不改任何数据、不动 crop_report.json。

用法
----
    python scripts/tools/probe_resolution.py            抽样 24 幅
    python scripts/tools/probe_resolution.py -n 0       全部图幅
    python scripts/tools/probe_resolution.py -n 60      抽样 60 幅
    python scripts/tools/probe_resolution.py --apply 1  把第①档写进 config.yaml
"""
import argparse
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import cv2
import yaml
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
_C = None


def _load_crop_module(script_path):
    """加载 01_crop.py 里的算法函数（借它的纠斜/外框/内容边界）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cropmod", script_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def probe_one(args):
    """返回 (文件名, 内容区宽, 内容区高) 或 (文件名, None, 原因)。"""
    path, script, cfg_crop = args
    try:
        c = _load_crop_module(script)
        img = c.imread_bgr(path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if cfg_crop.get("deskew", True):
            rng = cfg_crop.get("deskew_range", [-3.0, 3.0])
            a = c.estimate_skew(gray, rng[0], rng[1], cfg_crop.get("deskew_step", 0.02))
            img = c.rotate(img, a)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ob = c.find_outer_box(gray) or c.ink_bbox(gray)
        if ob is None:
            return os.path.basename(path), None, "未检出图廓"
        x, y, w, h = ob
        band = int(cfg_crop.get("outer_band", 0.025) * min(w, h))
        region = gray[y + band:y + h - band, x + band:x + w - band]
        if region.size == 0:
            return os.path.basename(path), None, "区域为空"
        ce = c.content_extent(region,
                              cfg_crop.get("density_threshold", 0.10),
                              cfg_crop.get("density_window", 20))
        if ce is None:
            return os.path.basename(path), region.shape[1], region.shape[0]
        return os.path.basename(path), ce[2], ce[3]
    except Exception as e:
        return os.path.basename(path), None, str(e)[:40]


def bar(v, lo, hi, width=28):
    if hi <= lo:
        return " " * width
    n = int(round((v - lo) / (hi - lo) * width))
    return "█" * max(0, min(width, n))


def main():
    ap = argparse.ArgumentParser(description="探测扫描件尺寸并推荐裁切分辨率")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-n", "--num", type=int, default=24,
                    help="抽样幅数，0 表示全部（默认 24）")
    ap.add_argument("--apply", type=int, choices=[1, 2, 3, 4],
                    help="把第 N 档建议写入 config.yaml 的 crop.out_size")
    a = ap.parse_args()

    cfgp = os.path.abspath(a.config)
    if not os.path.exists(cfgp):
        sys.exit("找不到 %s，请先复制 config.example.yaml" % a.config)
    cfg = yaml.safe_load(open(cfgp, encoding="utf-8"))
    base = os.path.dirname(cfgp)

    indir = os.path.join(base, cfg["paths"]["input"])
    if not os.path.isdir(indir):
        sys.exit("输入目录不存在: %s" % indir)
    script = os.path.join(base, "scripts", "01_crop.py")
    if not os.path.exists(script):
        sys.exit("找不到 scripts/01_crop.py")

    excl = set(cfg["crop"].get("exclude", []))
    files = sorted(f for f in os.listdir(indir)
                   if os.path.splitext(f)[1].lower() in IMG_EXT
                   and os.path.splitext(f)[0] not in excl)
    if not files:
        sys.exit("输入目录里没有图片: %s" % indir)

    total = len(files)
    if a.num and a.num < total:
        idx = [int(i * (total - 1) / max(a.num - 1, 1)) for i in range(a.num)]
        files = [files[i] for i in sorted(set(idx))]

    print("=" * 66)
    print("  扫描件尺寸探测")
    print("=" * 66)
    print()
    print("  输入目录: %s" % indir)
    print("  抽样:     %d 幅（共 %d 幅）" % (len(files), total))
    print()
    print("  正在逐幅测量（只做检测，不写任何文件）...")

    tasks = [(os.path.join(indir, f), script, cfg["crop"]) for f in files]
    results = []
    with ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as ex:
        for r in ex.map(probe_one, tasks):
            results.append(r)

    ok = [(n, w, h) for n, w, h in results if w]
    bad = [(n, r) for n, w, r in results if not w]
    if not ok:
        print("\n  [X] 没有成功测量的图幅，无法给出建议")
        for n, r in bad[:5]:
            print("     %s: %s" % (n, r))
        return 1

    ws = [w for _, w, _ in ok]
    hs = [h for _, _, h in ok]
    ar = [w / h for _, w, h in ok]

    print("  测量完成: %d 幅成功%s" % (
        len(ok), "，%d 幅失败" % len(bad) if bad else ""))
    if bad:
        for n, r in bad[:3]:
            print("     [!] %s: %s" % (n, r))
    print()
    print("--- 内容区尺寸（裁到内容边界后、缩放前）---")
    print("  宽度   最小 %5d   中位 %5d   最大 %5d" % (min(ws), int(statistics.median(ws)), max(ws)))
    print("  高度   最小 %5d   中位 %5d   最大 %5d" % (min(hs), int(statistics.median(hs)), max(hs)))
    print("  宽高比 最小 %.3f   中位 %.3f   最大 %.3f" % (min(ar), statistics.median(ar), max(ar)))
    print()
    print("--- 宽度分布 ---")
    lo, hi = min(ws), max(ws)
    step = max(500, ((hi - lo) // 6 // 500 + 1) * 500)
    b0 = (lo // step) * step
    edges = list(range(b0, hi + step + 1, step))
    for e0, e1 in zip(edges, edges[1:]):
        n = sum(1 for w in ws if e0 <= w < e1)
        if n:
            print("  %5d-%-5d %s %d" % (e0, e1, bar(n, 0, max(1, len(ws)), 24), n))

    med_w, med_h = int(statistics.median(ws)), int(statistics.median(hs))
    max_w, max_h = max(ws), max(hs)
    med_ar = statistics.median(ar)

    print()
    print("--- 建议（按你的用途选）---")
    print()
    print("  ① [4500, 3500]   轻微缩放，尺寸统一")
    print("     与多数图幅的内容比例最接近（中位宽高比 %.3f，目标 1.286）。" % med_ar)
    print("     用于经纬度配准时选这个 —— 图幅本来就要铺满固定的经纬度矩形。")
    print()
    print("  ② [%d, %d]   保留最大图幅的原始分辨率" % (max_w, max_h))
    print("     完全不下采样，代价是小图幅会被放大、文件较大。")
    print()
    print("  ③ [%d, %d]   约 2/3 尺寸" % (int(med_w * 2 / 3 / 10) * 10, int(med_h * 2 / 3 / 10) * 10))
    print("     适合屏幕浏览、做 PPT。")
    print()
    print("  ④ original        不缩放，各幅保持原始像素")
    print("     尺寸不统一（本项目实测中位 %dx%d），但零损失。" % (med_w, med_h))
    print("     只想裁掉黑边白边、不需要统一尺寸时选它。")
    print()

    # 比例离散度提示
    if max(ar) - min(ar) > 0.15:
        print("  [!] 各幅宽高比差异较大（%.3f ~ %.3f）。" % (min(ar), max(ar)))
        print("     若用固定 out_size 强制拉伸，比例偏离大的图幅会明显变形。")
        print("     建议改用保持比例模式： out_size 配 keep_aspect: true,")
        print("     或直接命令行加 k，例如  -s 4500x3500k")
        print()
    # 异常比例：很可能是接图表、封面之类混进来了
    odd = [(n, w, h) for n, w, h in ok if not (0.9 <= w / h <= 1.9)]
    if odd:
        print("  [!] 检测到 %d 幅宽高比异常（正常地图约 0.9~1.9）：" % len(odd))
        for n, w, h in odd[:6]:
            print("        %-28s %dx%d  比例 %.2f" % (n[:26], w, h, w / h))
        print("      这些多半不是地图（接图表、封面、说明页），建议把文件名")
        print("      （不含扩展名）加进 crop.exclude，然后重新探测。")
        print()

    if max(ws) > med_w * 1.25 or max(hs) > med_h * 1.25:
        print("  [!] 有图幅明显大于中位数（最大 %dx%d vs 中位 %dx%d），"
              % (max_w, max_h, med_w, med_h))
        print("     说明扫描分辨率不一致。建议统一到中位附近，别按最大那幅设。")
        print()

    print("--- 怎么用 ---")
    print()
    print("  改 config.yaml:")
    print("    crop:")
    print("      out_size: [4500, 3500]")
    print()
    print("  或者不改配置，直接命令行指定（更快试）:")
    print("    python scripts/01_crop.py -s 4500x3500        # 拉伸到该尺寸")
    print("    python scripts/01_crop.py -s 4500x3500k       # 保持比例居中补白")
    print("    python scripts/01_crop.py -s original         # 不缩放")
    print()
    print("  把上面第①档写进配置文件:")
    print("    python scripts/tools/probe_resolution.py --apply 1")

    if a.apply:
        pick = {
            1: [4500, 3500],
            2: [max_w, max_h],
            3: [int(med_w * 2 / 3 / 10) * 10, int(med_h * 2 / 3 / 10) * 10],
            4: None,
        }[a.apply]
        cfg["crop"]["out_size"] = pick
        if a.apply == 4:
            cfg["crop"]["keep_aspect"] = False
        with open(cfgp, "w", encoding="utf-8", newline="\n") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        print()
        print("=" * 66)
        print("  已写入 %s" % a.config)
        print("  crop.out_size = %s" % (pick if pick else "None（保持原始像素）"))
        print("=" * 66)

    return 0


if __name__ == "__main__":
    sys.exit(main())
