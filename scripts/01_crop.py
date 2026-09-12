# -*- coding: utf-8 -*-
"""
01_crop.py — 批量裁切历史地形图扫描件

流程
  1. 自动纠斜        投影方差法, 在 ±range 度内搜索使横线最"水平"的角度
  2. 识别外框        形态学提取长直线 + 多阈值降级(细条则降阈重试)
  3. 排除外框线带    避免把图廓线本身当内容
  4. 识别内容边界    墨迹密度游程, 可跨越地图边缘的稀疏区
  5. 安全兜底        内容框不可信时退回外框内整个区域 —— 宁可留白, 绝不切内容
  6. 输出定尺寸灰度 PNG

用法
  python scripts/01_crop.py                        # 读取 ./config.yaml
  python scripts/01_crop.py -c my.yaml
  python scripts/01_crop.py -c my.yaml 2108-瑪瑙觀  # 只处理指定文件(便于单幅试跑)
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import yaml
from PIL import Image

Image.MAX_IMAGE_PIXELS = None          # 扫描件普遍超过 PIL 默认上限

IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


# --------------------------------------------------------------------------- #
#  IO —— 统一走 bytes, 规避 Windows 中文路径问题
# --------------------------------------------------------------------------- #
def imread_bgr(path):
    return cv2.cvtColor(np.array(Image.open(path).convert("RGB")), cv2.COLOR_RGB2BGR)


def imwrite_png(path, arr):
    ok, buf = cv2.imencode(".png", arr, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    if not ok:
        raise IOError("PNG 编码失败: %s" % path)
    buf.tofile(path)


# --------------------------------------------------------------------------- #
#  1. 纠斜
# --------------------------------------------------------------------------- #
def estimate_skew(gray, lo=-3.0, hi=3.0, step=0.02, work=1600):
    """按不同角度旋转, 取"行投影方差最大"的角度 —— 摆正时横线最锐利。"""
    sc = work / max(gray.shape)
    gs = cv2.resize(gray, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
    h, w = gs.shape

    def score(a):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        r = cv2.warpAffine(gs, M, (w, h), borderValue=255)
        core = (r < 128)[int(.05 * h):int(.95 * h), int(.10 * w):int(.90 * w)]
        return core.sum(axis=1).var()

    angles = np.arange(lo, hi + step, step)
    return float(angles[int(np.argmax([score(a) for a in angles]))])


def rotate(img, angle, border=255):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LANCZOS4,
                          borderValue=(border,) * (3 if img.ndim == 3 else 1))


# --------------------------------------------------------------------------- #
#  2. 外框检测
# --------------------------------------------------------------------------- #
def find_outer_box(gray):
    """返回 (x, y, w, h) 或 None。

    做法: 二值化后用长核开运算只留下贯穿性长直线, 再做投影找边界。
    关键点是"多阈值降级": 阈值高时线太淡会只检出其中一条边,
    得到细条矩形(例如 4800x21), 此时必须降阈重试, 否则后续会误裁。
    """
    H, W = gray.shape
    ret, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_OTSU)
    mask = (gray < ret).astype(np.uint8) * 255

    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (max(1, W // 40), 1))
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(1, H // 40)))
    proj_h = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kh).sum(axis=1) / 255.0
    proj_v = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kv).sum(axis=0) / 255.0

    for thr in (0.30, 0.22, 0.16, 0.12, 0.09, 0.07):
        hi = np.where(proj_h > W * thr)[0]
        vi = np.where(proj_v > H * thr)[0]
        if len(hi) < 2 or len(vi) < 2:
            continue
        x0, y0 = int(vi[0]), int(hi[0])
        w, h = int(vi[-1] - vi[0]), int(hi[-1] - hi[0])
        if w < 0.4 * W or h < 0.4 * H:
            continue                      # 细条 → 降阈重试
        if 0.7 <= w / max(h, 1) <= 1.9:   # 图幅宽高比合理区间
            return x0, y0, w, h
    return None


def ink_bbox(gray):
    """兜底: 整幅的墨迹外接矩形。"""
    ret, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_OTSU)
    ys, xs = np.where(gray < ret)
    if ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), \
        int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


# --------------------------------------------------------------------------- #
#  4. 内容边界
# --------------------------------------------------------------------------- #
def content_extent(region, thr, win):
    """在给定区域内找墨迹密集区的外沿。

    逐行/逐列统计墨迹占比并做小幅平滑, 再取"连续 win 个像素都达标"的
    最外端作为边界 —— 连续窗口是为了滤掉孤立噪点与装订线。
    """
    H, W = region.shape
    ret, _ = cv2.threshold(region, 0, 255, cv2.THRESH_OTSU)
    mask = (region < ret).astype(np.uint8) * 255
    row = np.convolve(mask.sum(axis=1) / 255.0 / W, np.ones(7) / 7, mode="same")
    col = np.convolve(mask.sum(axis=0) / 255.0 / H, np.ones(7) / 7, mode="same")

    def edges(prof, t):
        over, run, lo, hi = prof >= t, 0, None, None
        for i, o in enumerate(over):
            if o:
                run += 1
                if run >= win and lo is None:
                    lo = i - win + 1
                hi = i
            else:
                run = 0
        return lo, hi

    t0, t1 = edges(row, thr)
    l0, l1 = edges(col, thr * 0.8)        # 左右方向略放宽, 防止竖排注记被切
    if None in (t0, t1, l0, l1):
        return None
    return l0, t0, l1 - l0, t1 - t0


# --------------------------------------------------------------------------- #
#  主流程
# --------------------------------------------------------------------------- #
def process_one(path, cfg, name):
    c = cfg["crop"]
    rec = {"file": name, "status": "ok"}
    img = imread_bgr(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # --- 1 纠斜 ---
    angle = 0.0
    if c.get("deskew", True):
        rng = c.get("deskew_range", [-3.0, 3.0])
        angle = estimate_skew(gray, rng[0], rng[1], c.get("deskew_step", 0.02))
        img = rotate(img, angle)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    rec["angle"] = round(angle, 3)

    # --- 2 外框 ---
    ob = find_outer_box(gray)
    if ob is None:
        ob = ink_bbox(gray)
        if ob is None:
            rec.update(status="fail", reason="既未检出外框, 也无墨迹")
            return rec
        rec["outer_rebuild"] = "ink_bbox"
    x, y, w, h = ob

    # 外框合理性复核: 太白/太窄/宽高比离谱 → 同样退回墨迹外接矩形
    if (w < 0.35 * gray.shape[1] or h < 0.35 * gray.shape[0]
            or not (0.5 <= w / max(h, 1) <= 2.3)):
        ib = ink_bbox(gray)
        if ib is None:
            rec.update(status="fail", reason="外框不可信且无墨迹兜底")
            return rec
        x, y, w, h = ib
        rec["outer_rebuild"] = "ink_bbox"
    rec["outer"] = [int(x), int(y), int(w), int(h)]

    # --- 3 排除外框线带 ---
    band = int(c.get("outer_band", 0.025) * min(w, h))
    region = gray[y + band:y + h - band, x + band:x + w - band]
    if region.size == 0:
        rec.update(status="fail", reason="外框线带排完后区域为空")
        return rec

    # --- 4 内容边界 ---
    ce = content_extent(region, c.get("density_threshold", 0.10),
                        c.get("density_window", 20))
    ROW, COL = region.shape
    if ce is None:
        cx, cy, cw, ch = 0, 0, COL, ROW
        rec["used_fallback"] = "content_fail_safe"
    else:
        cx, cy, cw, ch = ce
        # --- 5 安全兜底 ---
        rw, rh = cw / COL, ch / ROW
        off_w = abs((cx + cw / 2) - COL / 2) / COL
        off_h = abs((cy + ch / 2) - ROW / 2) / ROW
        if (name in set(c.get("force_safe", []))
                or rw < c.get("safe_ratio", 0.72)
                or rh < c.get("safe_ratio", 0.72)
                or off_w > c.get("safe_offset", 0.15)
                or off_h > c.get("safe_offset", 0.15)):
            cx, cy, cw, ch = 0, 0, COL, ROW
            rec["used_fallback"] = "content_clip_safe"
        rec["ratios"] = [round(rw, 3), round(rh, 3)]

    # --- 6 裁切输出 ---
    x0, y0 = x + band + cx, y + band + cy
    x1, y1 = x0 + cw, y0 + ch
    if x1 - x0 < 100 or y1 - y0 < 100:
        rec.update(status="fail", reason="裁切区域过小")
        return rec

    ow, oh = c.get("out_size", [4500, 3500])
    crop = cv2.resize(img[y0:y1, x0:x1], (ow, oh), interpolation=cv2.INTER_LANCZOS4)
    out = os.path.join(cfg["_crop_dir"], name + "_inner.png")
    imwrite_png(out, cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))

    rec["inner"] = [int(x0), int(y0), int(x1), int(y1)]
    rec["flag"] = "safe" if rec.get("used_fallback") or rec.get("outer_rebuild") else "ok"
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("only", nargs="*", help="只处理这些文件名(不含扩展名)")
    a = ap.parse_args()

    cfg = load_config(a.config)
    inp, cro = cfg["_input_dir"], cfg["_crop_dir"]
    os.makedirs(cro, exist_ok=True)

    excl = set(cfg["crop"].get("exclude", []))
    files = sorted(p for p in Path(inp).iterdir()
                   if p.suffix.lower() in IMG_EXT and p.stem not in excl)
    if a.only:
        want = set(a.only)
        files = [p for p in files if p.stem in want]
    if not files:
        print("输入目录没有可处理图片:", inp)
        return 1

    print("待处理 %d 幅   输入: %s\n输出: %s\n" % (len(files), inp, cro))
    t0, recs = time.time(), []
    for p in files:
        try:
            r = process_one(str(p), cfg, p.stem)
        except Exception as e:                       # 单幅失败不影响整批
            import traceback
            traceback.print_exc()
            r = {"file": p.stem, "status": "fail", "reason": str(e)}
        recs.append(r)
        print("%-32s %-5s %-18s %s" % (
            p.stem, r.get("status"),
            r.get("flag") or r.get("reason", ""),
            ("angle %+.2f" % r["angle"]) if "angle" in r else ""))

    ok = sum(1 for r in recs if r.get("status") == "ok")
    safe = sum(1 for r in recs if r.get("flag") == "safe")
    rep = os.path.join(cro, "crop_report.json")
    with open(rep, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=1)
    print("\n完成 %d/%d  其中安全兜底 %d 幅   耗时 %.0fs" % (ok, len(recs), safe, time.time() - t0))
    print("报告:", rep)
    return 0


def load_config(path):
    p = Path(path)
    if not p.exists():
        ex = p.with_name("config.example.yaml")
        sys.exit("找不到 %s\n请先复制 %s 为 config.yaml 并按需修改" % (p, ex.name))
    cfg = yaml.safe_load(open(p, encoding="utf-8"))
    base = p.parent
    for k in ("input", "crop", "geo"):
        cfg["_" + k + "_dir"] = str((base / cfg["paths"][k]).resolve())
    return cfg


if __name__ == "__main__":
    sys.exit(main())
