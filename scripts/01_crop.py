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
    # 压缩等级 1。
    # 实测(4500x3500 灰度图): 等级6 需 1.004s, 等级1 只需 0.355s —— 快 2.8 倍,
    # 而文件仅从 9.3MB 增到 9.8MB(+5%)。这批图是灰度线条图, 等级 6 以上
    # 压缩比几乎不再提升却极慢, 故取 1。
    ok, buf = cv2.imencode(".png", arr, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        raise IOError("PNG 编码失败: %s" % path)
    buf.tofile(path)


def detect_color_ratio(img_bgr, sat_thr=150, val_thr=40):
    """估算"内容有颜色"的像素占比，用于 crop.color: auto。

    这里的关键是**阈值要取高**（S > 150），而不是随便取个 60。
    实测两类扫描件：

        湖北五万分一地形图（黑白+纸张泛黄）
            S 均值 44~49,  S 中位 46~50,  S>150 占比 0.00%
        民国全国交通图（整幅带色）
            S 均值 71~82,  S 中位 74~77,  S>150 占比 0.75~4.30%

    泛黄的纸张会让 S 升到 40~50，若阈值取 60 就会把所有泛黄老图都误判成彩色；
    取 150 则只捕捉真正的内容着色（红蓝线条、彩色底纹），两类差值很大，分得开。

    返回高饱和像素占比；判定阈值由 crop.color_sat_ratio 控制（默认 0.001）。
    """
    if img_bgr.ndim == 2:
        return 0.0
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    return float(((s > sat_thr) & (v > val_thr)).mean())


# --------------------------------------------------------------------------- #
#  1. 纠斜
# --------------------------------------------------------------------------- #
def estimate_skew(gray, lo=-3.0, hi=3.0, step=0.02, work=1600):
    """按不同角度旋转, 取"行投影方差最大"的角度 —— 摆正时横线最锐利。

    粗到细两级搜索: 先用粗步长定位峰值大致位置, 再在附近用细步长精搜。
    该目标函数是单峰的, 所以两级结果与全量扫描一致, 但快得多。
    实测(-3~3 度, 步长 0.02): 301 次全量 0.796s -> 31+21 次 0.147s, 角度完全相同。
    """
    sc = work / max(gray.shape)
    gs = cv2.resize(gray, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
    h, w = gs.shape

    def score(a):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        r = cv2.warpAffine(gs, M, (w, h), borderValue=255)
        core = (r < 128)[int(.05 * h):int(.95 * h), int(.10 * w):int(.90 * w)]
        return core.sum(axis=1).var()

    coarse = max(step * 10, 0.2)
    a1 = np.arange(lo, hi + coarse, coarse)
    best = float(a1[int(np.argmax([score(a) for a in a1]))])
    a2 = np.arange(max(lo, best - coarse), min(hi, best + coarse) + step, step)
    return float(a2[int(np.argmax([score(a) for a in a2]))])


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
        """取"连续 win 个像素都达标"的最外端作为边界。

        注意后边界(hi)也必须受连续窗口约束 —— 否则末尾一个孤立噪点
        就能把边界拉出去。实测: 内容真实范围 50~400、900 处有一个噪点时,
        无约束会把下边界从 400 拉到 900(多裁 500px 空白进来)。
        """
        over, run, lo, hi = prof >= t, 0, None, None
        for i, o in enumerate(over):
            if o:
                run += 1
                if run >= win:            # 必须连续达标才算数
                    if lo is None:
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
    c = dict(cfg["crop"])                 # 复制一份, 便于逐幅覆盖
    # 逐幅参数覆盖: 个别图幅(如大片湖区、内容极稀疏)需要单独放宽阈值时用,
    # 不必为了一幅去改全局参数, 更不必把全部图幅重跑一遍。
    # 配置写法:
    #   crop:
    #     per_sheet:
    #       "1117-分水嘴": {density_threshold: 0.06}
    ov = (c.get("per_sheet") or {}).get(name) or {}
    c.update(ov)
    rec = {"file": name, "status": "ok"}
    if ov:
        rec["per_sheet"] = ov
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

    crop = img[y0:y1, x0:x1]
    sz = c.get("out_size")
    if not sz or sz[0] in (None, 0) or sz[1] in (None, 0):
        # out_size: null —— 保持裁切后的原始像素, 不缩放。
        # 适用于"只想裁掉黑边白边"、不需要统一尺寸的场景。
        rec["out_size"] = "original"
    elif c.get("keep_aspect"):
        # keep_aspect: true —— 按内容比例缩放, 居中补白到 out_size。
        # 不会拉伸变形, 代价是四周可能有一圈很窄的白边。
        # 图幅比例与 out_size 差得较多时必须用它, 否则内容会被拉扭。
        oh_, ow_ = sz[1], sz[0]
        hh, ww = crop.shape[:2]
        scale = min(ow_ / ww, oh_ / hh)
        nw, nh = max(1, int(round(ww * scale))), max(1, int(round(hh * scale)))
        resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
        canvas = np.full((oh_, ow_, 3), 255, np.uint8)
        ox, oy = (ow_ - nw) // 2, (oh_ - nh) // 2
        canvas[oy:oy + nh, ox:ox + nw] = resized
        crop = canvas
        rec["out_size"] = "keep_aspect"
    else:
        # 默认: 强制缩放到 out_size。配合经纬度网格使用 ——
        # 图幅本来就要铺满固定的经纬度矩形, 轻微拉伸是预期行为。
        crop = cv2.resize(crop, (sz[0], sz[1]), interpolation=cv2.INTER_LANCZOS4)
        rec["out_size"] = "%dx%d" % (sz[0], sz[1])

    out = os.path.join(cfg["_crop_dir"], name + "_inner.png")

    # 色彩: auto 按内容饱和度自动判断, 也可强制 grayscale / color。
    # 默认 auto —— 地形图这类黑白扫描件会被压成灰度（省一半空间）,
    # 而交通图、水系图这类**内容本身有颜色**的必须保留彩色, 否则颜色丢失。
    cmode = str(c.get("color", "auto")).lower()
    if cmode == "auto":
        frac = detect_color_ratio(crop)
        thr = float(c.get("color_sat_ratio", 0.001))
        use_color = frac >= thr
        rec["color"] = "%s(%.3f%%)" % ("color" if use_color else "gray", frac * 100)
    else:
        use_color = (cmode in ("color", "colour", "rgb", "true", "彩色"))
        rec["color"] = "color" if use_color else "gray"

    imwrite_png(out, crop if use_color else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))

    rec["inner"] = [int(x0), int(y0), int(x1), int(y1)]
    rec["flag"] = "safe" if rec.get("used_fallback") or rec.get("outer_rebuild") else "ok"
    return rec


def parse_size(token):
    """解析命令行给的尺寸。接受这几种写法:
         3000x2000    3000X2000    3000*2000    3000,2000
         3000x2000k   —— 末尾加 k 表示"保持比例、居中补白"(不拉伸变形)
         original     (或 none / null) 不缩放, 保持裁切后的原始像素
    返回 (size, keep_aspect):
         size = [w, h] 或 "original" 或 None
         keep_aspect = True / False / None(不覆盖配置)
    """
    if token is None:
        return None, None
    t = str(token).strip().lower()
    if t in ("original", "orig", "none", "null", "原始"):
        return "original", None

    keep = None
    if t.endswith("k"):                 # 3000x2000k -> 保持比例
        keep = True
        t = t[:-1].strip()
        if not t:
            raise SystemExit("尺寸格式不对。k 前面要有尺寸，例如： 3000x2000k")

    joined = t.replace("x", ",").replace("*", ",").replace("，", ",")
    parts = [p for p in joined.split(",") if p]
    if len(parts) != 2:
        raise SystemExit("尺寸格式不对，应为 宽x高。例如： -s 3000x2000\n"
                         "（末尾加 k 表示保持比例： -s 3000x2000k）")
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError:
        raise SystemExit("尺寸必须是整数。例如： -s 3000x2000")
    if w < 100 or h < 100:
        raise SystemExit("尺寸太小了（至少 100x100）： %dx%d" % (w, h))
    return [w, h], keep


def main():
    ap = argparse.ArgumentParser(
        description="批量裁切历史地形图扫描件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例：\n"
               "  python scripts/01_crop.py -s 3000x2000                 指定输出尺寸\n"
               "  python scripts/01_crop.py -s 3000x2000 --keep-aspect   保持比例、居中补白\n"
               "  python scripts/01_crop.py -s original                  不缩放，保留原始像素\n"
               "  python scripts/01_crop.py -s 3000x2000 1117-分水嘴      只重跑某一幅\n")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-s", "--size", metavar="WxH",
                    help="输出尺寸，覆盖配置文件里的 out_size。"
                         "如 3000x2000；写 original 表示不缩放")
    ap.add_argument("--keep-aspect", action="store_true", default=None,
                    help="保持比例缩放、居中补白（不拉伸变形）")
    ap.add_argument("--stretch", action="store_true", default=None,
                    help="强制拉伸到指定尺寸（与 --keep-aspect 相反）")
    ap.add_argument("--color", choices=["auto", "gray", "color"], default=None,
                    help="输出色彩，覆盖配置里的 crop.color："
                         "auto=自动判断(默认)  gray=强制灰度  color=强制彩色")
    ap.add_argument("only", nargs="*", help="只处理这些文件名(不含扩展名)")
    a = ap.parse_args()

    cfg = load_config(a.config)
    inp, cro = cfg["_input_dir"], cfg["_crop_dir"]
    os.makedirs(cro, exist_ok=True)

    # 命令行覆盖配置
    cmd_size, cmd_keep = parse_size(a.size)
    if cmd_size == "original":
        cfg["crop"]["out_size"] = None
        print("输出尺寸：保持原始像素（命令行指定）")
    elif cmd_size:
        cfg["crop"]["out_size"] = cmd_size
        print("输出尺寸：%d x %d（命令行指定，覆盖配置）" % (cmd_size[0], cmd_size[1]))
    if cmd_keep:
        cfg["crop"]["keep_aspect"] = True
        print("缩放方式：保持比例，居中补白（尺寸末尾的 k）")
    if a.keep_aspect:
        cfg["crop"]["keep_aspect"] = True
        print("缩放方式：保持比例，居中补白")
    elif a.stretch:
        cfg["crop"]["keep_aspect"] = False
        print("缩放方式：强制拉伸到目标尺寸")
    if a.color:
        cfg["crop"]["color"] = {"auto": "auto", "gray": "grayscale",
                                "color": "color"}[a.color]
        print("输出色彩：%s" % {"auto": "自动判断", "gray": "强制灰度",
                                "color": "强制彩色"}[a.color])
    if cmd_size or cmd_keep or a.keep_aspect or a.stretch or a.color:
        print()

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

    # 合并写入: 只跑单幅时不要冲掉其余图幅的历史记录。
    # 否则 `python scripts/01_crop.py 1117-分水嘴` 会把几百条报告变成 1 条,
    # 之后想回顾"哪几幅走过安全兜底"就没数据了。
    old = {}
    if os.path.exists(rep):
        try:
            for r in json.load(open(rep, encoding="utf-8")):
                if r.get("file"):
                    old[r["file"]] = r
        except Exception:
            pass
    for r in recs:
        old[r["file"]] = r
    with open(rep, "w", encoding="utf-8") as f:
        json.dump([old[k] for k in sorted(old)], f, ensure_ascii=False, indent=1)

    print("\n完成 %d/%d  其中安全兜底 %d 幅   耗时 %.0fs"
          % (ok, len(recs), safe, time.time() - t0))
    print("报告: %s  (累计 %d 条)" % (rep, len(old)))
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
