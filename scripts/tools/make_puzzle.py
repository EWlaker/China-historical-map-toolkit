# -*- coding: utf-8 -*-
"""
make_puzzle.py — 生成"拼图工作台"网页，用拖拽的方式确定图幅位置关系

解决什么问题
------------
有些扫描件**没有图号、没有接图表、图上也没有经纬度**（例如民国全国交通图），
这时既算不出坐标、也没法自动排布。但它们本来是一张整图切开的 ——
**人一眼就能看出哪两幅相邻**，只是没有工具把这个判断记录下来。

本工具把裁好的图做成缩略图，生成一个可拖拽的网页。你像拼拼图一样把图幅
摆到正确位置，导出布局 JSON，再交给 assemble_by_layout.py 拼成整幅。

它输出的是"相对位置关系"，不涉及地理坐标 ——
需要真实坐标的话那是另一条路（见 docs/命名规则与接图表.md）。

用法
----
    python scripts/tools/make_puzzle.py                # 生成 work/puzzle.html
    python scripts/tools/make_puzzle.py --thumb 240    # 指定缩略图宽度
    python scripts/tools/make_puzzle.py --open         # 生成后直接打开浏览器

生成的 HTML 是自包含的（缩略图以 base64 内嵌），拷到哪台机器都能打开，
不需要联网、不需要装任何东西。
"""
import argparse
import base64
import io
import json
import os
import sys
import webbrowser

from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def make_thumb(path, width):
    """读图 -> 缩略图 -> base64(JPEG)。用 PIL 以兼容中文路径。"""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    nh = max(1, int(round(h * width / w)))
    im = im.resize((width, nh), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii"), w, h


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>拼图工作台 — 确定图幅位置关系</title>
<style>
  :root{
    --bg:#f6f6f4; --panel:#ffffff; --line:#d8d8d2; --ink:#22221f;
    --dim:#8a8a80; --accent:#2f6f4f; --accent2:#c9552e;
    --cell:110px;
  }
  .zoombar{display:flex;align-items:center;gap:6px;margin-right:4px}
  .zoombar button{padding:4px 10px;font-size:13px;line-height:1}
  .zoombar .pct{font-size:12px;color:var(--dim);min-width:44px;text-align:right}
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.5 "Segoe UI","Microsoft YaHei",sans-serif;
       background:var(--bg);color:var(--ink);overflow:hidden}
  header{height:52px;display:flex;align-items:center;gap:14px;padding:0 16px;
         background:var(--panel);border-bottom:1px solid var(--line)}
  header h1{font-size:15px;margin:0;font-weight:600}
  header .sp{flex:1}
  button{font:inherit;padding:6px 14px;border:1px solid var(--line);
         background:#fff;border-radius:6px;cursor:pointer;color:var(--ink)}
  button:hover{border-color:var(--accent);color:var(--accent)}
  button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
  button.primary:hover{opacity:.9;color:#fff}
  button:disabled{opacity:.4;cursor:not-allowed}
  #wrap{display:flex;height:calc(100vh - 52px)}
  #tray{width:220px;flex:none;background:var(--panel);border-right:1px solid var(--line);
        overflow-y:auto;padding:10px}
  #tray h2{font-size:12px;color:var(--dim);margin:0 0 8px;font-weight:600;
           letter-spacing:.5px;text-transform:uppercase}
  .chip{border:1px solid var(--line);border-radius:6px;margin-bottom:8px;
        background:#fff;cursor:grab;overflow:hidden;position:relative}
  .chip img{display:block;width:100%;pointer-events:none}
  .chip .nm{font-size:11px;padding:3px 6px;color:var(--dim);
            white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
            border-top:1px solid var(--line)}
  .chip.dragging{opacity:.4}
  #boardwrap{flex:1;overflow:auto;position:relative;cursor:grab;
             background:
               linear-gradient(90deg,var(--line) 1px,transparent 1px) 0 0/var(--cell) var(--cell),
               linear-gradient(var(--line) 1px,transparent 1px) 0 0/var(--cell) var(--cell),
               var(--bg)}
  #board{position:relative;min-width:100%;min-height:100%}
  .tile{position:absolute;border:2px solid #bbb;border-radius:3px;overflow:hidden;
        background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.18);cursor:grab}
  #boardwrap.panning{cursor:grabbing}
  #boardwrap.panning .tile{cursor:grabbing}
  .tile img{display:block;width:100%;height:100%;pointer-events:none;user-select:none}
  .tile.hover{border-color:var(--accent2);box-shadow:0 0 0 3px rgba(201,85,46,.25);
              pointer-events:none}
  .tile .lbl{position:absolute;left:0;bottom:0;right:0;font-size:10px;color:#fff;
             background:rgba(0,0,0,.55);padding:1px 4px;white-space:nowrap;
             overflow:hidden;text-overflow:ellipsis;pointer-events:none}
  #hint{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);
        background:rgba(34,34,31,.88);color:#fff;padding:7px 16px;border-radius:20px;
        font-size:12px;pointer-events:none;opacity:0;transition:opacity .25s}
  #hint.on{opacity:1}
  dialog{border:none;border-radius:10px;padding:0;max-width:min(760px,92vw);
         box-shadow:0 12px 48px rgba(0,0,0,.3)}
  dialog::backdrop{background:rgba(0,0,0,.35)}
  .dlg-h{padding:14px 18px;border-bottom:1px solid var(--line);font-weight:600}
  .dlg-b{padding:16px 18px;max-height:56vh;overflow:auto}
  .dlg-f{padding:12px 18px;border-top:1px solid var(--line);display:flex;gap:10px;
         justify-content:flex-end}
  textarea{width:100%;height:230px;font:12px/1.5 Consolas,monospace;
           border:1px solid var(--line);border-radius:6px;padding:10px;resize:vertical}
  table{border-collapse:collapse;font-size:12px;width:100%}
  th,td{border:1px solid var(--line);padding:4px 8px;text-align:left}
  th{background:#f0f0ec}
  .stat{color:var(--dim);font-size:12px}
</style>
</head>
<body>
<header>
  <h1>拼图工作台</h1>
  <span class="stat" id="gen"></span>
  <span class="stat" id="stat"></span>
  <span class="sp"></span>
  <span class="zoombar">
    <button id="btnZoomOut" title="缩小（滚轮也可以）">&minus;</button>
    <span class="pct" id="zoomPct">100%</span>
    <button id="btnZoomIn" title="放大（滚轮也可以）">+</button>
    <button id="btnZoomFit" title="缩放到适合窗口">适应</button>
  </span>
  <button id="btnAuto">自动排布</button>
  <button id="btnClear">全部取回</button>
  <button class="primary" id="btnExport" disabled>导出布局</button>
</header>

<div id="wrap">
  <div id="tray">
    <h2>待放置 <span id="left"></span></h2>
    <div style="font-size:11px;color:var(--dim);line-height:1.7;margin-bottom:10px">
      滚轮缩放（以屏幕中心）<br>空白处拖动平移 · 拖图块摆放<br>双击退回 · F 适应窗口
    </div>
    <div id="chips"></div>
  </div>
  <div id="boardwrap"><div id="board"></div></div>
</div>

<div id="hint"></div>

<dialog id="dlg">
  <div class="dlg-h">布局结果</div>
  <div class="dlg-b">
    <p class="stat" id="summary"></p>
    <table id="tbl"></table>
    <p class="stat" style="margin-top:14px">把下面这段 JSON 存成 <b>puzzle_layout.json</b>，
    然后运行：<br>
    <code>python scripts/tools/assemble_by_layout.py puzzle_layout.json</code></p>
    <textarea id="json" readonly></textarea>
  </div>
  <div class="dlg-f">
    <button id="btnCopy">复制 JSON</button>
    <button id="btnSave">下载 JSON</button>
    <button class="primary" id="btnClose">关闭</button>
  </div>
</dialog>

<script>
const TILES = __TILES__;
const GAP = 4;
let CELL = 110;                       // 格子边长，滚轮可调
const CELL_MIN = 36, CELL_MAX = 420;  // 太小点不中，太大没意义
const BASE = 110;                     // 100% 时的格子尺寸

const board = document.getElementById('board');
const chips = document.getElementById('chips');
const wrap  = document.getElementById('boardwrap');
const hintEl = document.getElementById('hint');

let placed = {};          // name -> {el, col, row}
let dragName = null, dragFrom = null, ghost = null, hoverCell = null;
let dragOrigin = null;   // 从画布拖动时记下原位，供"拖到有图的格子 = 对调"用

function hint(msg){
  hintEl.textContent = msg; hintEl.classList.add('on');
  clearTimeout(hint._t); hint._t = setTimeout(()=>hintEl.classList.remove('on'), 2200);
}
function cellSize(){ return CELL + GAP; }

/* ---------------- 左栏缩略图 ---------------- */
function buildTray(){
  TILES.forEach(t=>{
    const d = document.createElement('div');
    d.className = 'chip'; d.draggable = true; d.dataset.name = t.name;
    d.innerHTML = `<img src="data:image/jpeg;base64,${t.thumb}">
                   <div class="nm">${t.label}</div>`;
    d.addEventListener('dragstart', e=>{
      dragName = t.name; dragFrom = 'tray';
      d.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', t.name);
    });
    d.addEventListener('dragend', ()=>d.classList.remove('dragging'));
    chips.appendChild(d);
  });
}

/* ---------------- 画布上的图块 ---------------- */
function tileOf(name){ return TILES.find(t=>t.name===name); }

function place(name, col, row){
  if (placed[name]) {                       // 已放置 -> 移动
    const p = placed[name];
    p.col = col; p.row = row;
    layoutTile(p);
    resizeBoard();
    return;
  }
  // 目标格被别的图占着
  const occ = Object.entries(placed).find(
      ([n, q]) => q.col === col && q.row === row && n !== name);
  if (occ){
    if (dragFrom === 'board' && dragOrigin){
      // 从画布上拖来的 -> **两幅对调位置**。
      // 原来这里是直接 return，可调用方已经把自己删掉了，
      // 于是那幅图凭空消失（用户报的"下面的会被覆盖掉"）。
      const [oname, oq] = occ;
      oq.col = dragOrigin.col; oq.row = dragOrigin.row;
      layoutTile(oq);
      hint('两幅已对调位置');
      dragOrigin = null;
    } else {
      hint('这一格已经有图了'); return;
    }
  }
  dragOrigin = null;
  const t = tileOf(name);
  if (!t){
    // 找不到对应的图幅定义。**不能抛异常** —— 抛了会中断后面的渲染，
    // 用户看到的是"图突然不见了"，控制台只有一行 JS 报错，无从判断。
    // 测试时误传标签文字就踩到过这个：那幅图凭空消失。
    hint('无法识别这个图幅，已忽略');
    console.warn('place(): TILES 里没有', name);
    return;
  }
  const el = document.createElement('div');
  el.className = 'tile'; el.style.width = CELL+'px'; el.style.height = CELL+'px';
  el.draggable = true;
  el.innerHTML = `<img src="data:image/jpeg;base64,${t.thumb}">
                  <div class="lbl">${t.label}</div>`;
  const p = {el, col, row};
  placed[name] = p;
  layoutTile(p);
  board.appendChild(el);

  el.addEventListener('dragstart', e=>{
    dragName = name; dragFrom = 'board';
    dragOrigin = {col: p.col, row: p.row};      // 记住原位，供对调用
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', name);
    setTimeout(()=>el.style.opacity = .35, 0);
  });
  el.addEventListener('dragend', ()=>{ el.style.opacity = 1; });
  el.addEventListener('dblclick', ()=>takeBack(name, true));
  sync();
  resizeBoard();          // 摆完要撑画布，否则滚不到新摆的位置
}
function layoutTile(p){
  p.el.style.left = (p.col*cellSize() + GAP) + 'px';
  p.el.style.top  = (p.row*cellSize() + GAP) + 'px';
}
function takeBack(name, redraw){
  const p = placed[name]; if(!p) return;
  p.el.remove(); delete placed[name];
  const chip = chips.querySelector(`.chip[data-name="${CSS.escape(name)}"]`);
  if (chip) chip.style.display = '';
  if (redraw) sync();
  resizeBoard();
}

/* ---------------- 缩放 ---------------- */
const zoomPct = document.getElementById('zoomPct');

function applyZoom(next){
  // 锚点固定为**屏幕中心**：先记下屏幕中心当前对应画布的哪个格子，
  // 缩放后把它滚回屏幕中心，视觉上就是"围绕中心放大/缩小"。
  next = Math.max(CELL_MIN, Math.min(CELL_MAX, next));
  if (Math.abs(next - CELL) < 0.01) return;
  const old = CELL;
  const ax = wrap.clientWidth / 2, ay = wrap.clientHeight / 2;
  const cx = (wrap.scrollLeft + ax) / (old + GAP);
  const cy = (wrap.scrollTop  + ay) / (old + GAP);
  CELL = next;
  relayout();
  wrap.scrollLeft = cx * (CELL + GAP) - ax;
  wrap.scrollTop  = cy * (CELL + GAP) - ay;
}
function relayout(){
  Object.values(placed).forEach(p=>{
    p.el.style.width = CELL+'px'; p.el.style.height = CELL+'px';
    layoutTile(p);
  });
  resizeBoard();
  zoomPct.textContent = Math.round(CELL / BASE * 100) + '%';
}

/* 把画布撑到内容大小。
   ⚠ 图块是 position:absolute，不占布局空间 —— 不显式设尺寸的话
     #board 永远只有容器那么大，滚动条滚不动、拖动平移也没反应。
   多留 PAD 一段余量：最后一列/行不贴边，也方便继续往右下拖。 */
const PAD = 3;                      // 额外留几个格子
function resizeBoard(){
  let maxC = -1, maxR = -1;
  Object.values(placed).forEach(p=>{
    maxC = Math.max(maxC, p.col);
    maxR = Math.max(maxR, p.row);
  });
  const step = CELL + GAP;
  const w = (maxC + 1 + PAD) * step;
  const h = (maxR + 1 + PAD) * step;
  board.style.width  = Math.max(w, wrap.clientWidth)  + 'px';
  board.style.height = Math.max(h, wrap.clientHeight) + 'px';
}
function zoomFit(){
  const n = Object.keys(placed).length;
  if (!n) return;
  const cols = Math.max(...Object.values(placed).map(p=>p.col)) + 1;
  const rows = Math.max(...Object.values(placed).map(p=>p.row)) + 1;
  const pad = 24;
  const w = (wrap.clientWidth - pad) / cols - GAP;
  const h = (wrap.clientHeight - pad) / rows - GAP;
  applyZoom(Math.min(w, h));
}

// 滚轮缩放：直接响应，不用按 Ctrl —— 拼图时看全局/看细节是最高频动作
wrap.addEventListener('wheel', e=>{
  e.preventDefault();
  const step = e.deltaY < 0 ? 1.12 : 1/1.12;
  applyZoom(CELL * step);        // 锚点固定屏幕中心，不看鼠标位置
}, {passive:false});

/* ---------------- 拖动平移 ----------------
   空白处按住左键拖动 = 平移画布；
   图块上的拖动仍然是移动图块（由 HTML5 drag 处理，不会走到这里）；
   中键在任何位置都能平移（CAD / 地图工具的习惯）。 */
let panning = null;
wrap.addEventListener('mousedown', e=>{
  const onTile = e.target.closest && e.target.closest('.tile');
  const isMiddle = (e.button === 1);
  if (e.button !== 0 && !isMiddle) return;
  if (onTile && !isMiddle) return;          // 图块上按左键 -> 交给 drag
  e.preventDefault();
  panning = {x: e.clientX, y: e.clientY,
             sl: wrap.scrollLeft, st: wrap.scrollTop, moved: false};
  wrap.classList.add('panning');
});
window.addEventListener('mousemove', e=>{
  if (!panning) return;
  const dx = e.clientX - panning.x, dy = e.clientY - panning.y;
  if (Math.abs(dx) > 2 || Math.abs(dy) > 2) panning.moved = true;
  wrap.scrollLeft = panning.sl - dx;
  wrap.scrollTop  = panning.st - dy;
});
window.addEventListener('mouseup', ()=>{
  if (!panning) return;
  panning = null;
  wrap.classList.remove('panning');
});
// 中键在很多浏览器里会触发自动滚动，屏蔽掉
wrap.addEventListener('auxclick', e=>{ if (e.button === 1) e.preventDefault(); });

document.getElementById('btnZoomIn').onclick  = ()=>applyZoom(CELL * 1.2);
document.getElementById('btnZoomOut').onclick = ()=>applyZoom(CELL / 1.2);
document.getElementById('btnZoomFit').onclick = zoomFit;

/* ---------------- 拖放 ---------------- */
function cellFromEvent(e){
  const r = board.getBoundingClientRect();
  const x = e.clientX - r.left + wrap.scrollLeft;
  const y = e.clientY - r.top  + wrap.scrollTop;
  return {col: Math.max(0, Math.round((x-GAP/2)/cellSize()-0.5)),
          row: Math.max(0, Math.round((y-GAP/2)/cellSize()-0.5))};
}
board.addEventListener('dragover', e=>{
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  const c = cellFromEvent(e);
  if (!hoverCell || hoverCell.col!==c.col || hoverCell.row!==c.row){
    hoverCell = c;
    if (ghost) ghost.remove();
    ghost = document.createElement('div');
    ghost.className = 'tile hover';
    ghost.style.width = CELL+'px'; ghost.style.height = CELL+'px';
    ghost.style.pointerEvents = 'none';   // 鼠标穿过它，否则会来回触发 dragleave
    ghost.style.left = (c.col*cellSize()+GAP)+'px';
    ghost.style.top  = (c.row*cellSize()+GAP)+'px';
    board.appendChild(ghost);
  }
});
board.addEventListener('dragleave', e=>{
  if (e.target === board && ghost){ ghost.remove(); ghost = null; hoverCell = null; }
});
board.addEventListener('drop', e=>{
  e.preventDefault();
  if (ghost){ ghost.remove(); ghost = null; }
  const name = e.dataTransfer.getData('text/plain') || dragName;
  if (!name) return;
  const c = cellFromEvent(e);
  if (dragFrom === 'board' && placed[name]){
    // 必须先摘掉 DOM 再删记录 —— 只删记录的话 place() 会以为是新图块而
    // 新建一个元素，旧元素留在原地变成幽灵图块（实测出现过同一幅两个）。
    // 自己已摘除，但原位记在 dragOrigin 里，place() 用它和目标格的图对调。
    placed[name].el.remove();
    delete placed[name];
  }
  place(name, c.col, c.row);
  hoverCell = null;
  const chip = chips.querySelector(`.chip[data-name="${CSS.escape(name)}"]`);
  if (chip) chip.style.display = 'none';
});

/* ---------------- 自动排布 ---------------- */
document.getElementById('btnAuto').onclick = ()=>{
  const cols = Math.ceil(Math.sqrt(TILES.length));
  TILES.forEach((t,i)=>{
    const col = i % cols, row = Math.floor(i / cols);
    place(t.name, col, row);
    const chip = chips.querySelector(`.chip[data-name="${CSS.escape(t.name)}"]`);
    if (chip) chip.style.display = 'none';
  });
  hint('已按顺序排好，接下来把它们拖到正确位置');
};
document.getElementById('btnClear').onclick = ()=>{
  Object.keys(placed).forEach(n=>takeBack(n, false));
  chips.querySelectorAll('.chip').forEach(c=>c.style.display='');
  sync(); resizeBoard();
};

/* ---------------- 状态同步 ---------------- */
function sync(){
  const n = Object.keys(placed).length, total = TILES.length;
  document.getElementById('left').textContent = `(${total-n})`;
  document.getElementById('stat').textContent = `已放置 ${n} / ${total}`;
  const btn = document.getElementById('btnExport');
  btn.disabled = (n === 0);
  btn.textContent = n === total ? '导出布局' : `导出布局 (${n}/${total})`;
}

/* ---------------- 导出 ---------------- */
function buildLayout(){
  const items = Object.entries(placed).map(([name,p])=>({
    name, label: tileOf(name).label, col: p.col, row: p.row
  }));
  const cols = Math.max(...items.map(i=>i.col), 0) + 1;
  const rows = Math.max(...items.map(i=>i.row), 0) + 1;
  // 归一化到从 0 开始
  const minC = Math.min(...items.map(i=>i.col));
  const minR = Math.min(...items.map(i=>i.row));
  items.forEach(i=>{ i.col -= minC; i.row -= minR; });
  return {version:1, grid:{cols, rows}, count:items.length, items};
}

document.getElementById('btnExport').onclick = ()=>{
  const L = buildLayout();
  const gaps = L.grid.cols*L.grid.rows - L.count;
  document.getElementById('summary').textContent =
    `${L.count} 幅排成 ${L.grid.cols} 列 × ${L.grid.rows} 行` +
    (gaps>0 ? `，有 ${gaps} 个空格` : '，网格已填满');
  const t = document.getElementById('tbl');
  t.innerHTML = '<tr><th>格子</th><th>图幅</th></tr>' +
    L.items.slice().sort((a,b)=>a.row-b.row||a.col-b.col)
      .map(i=>`<tr><td>第${i.row+1}行 第${i.col+1}列</td><td>${i.label}</td></tr>`).join('');
  document.getElementById('json').value = JSON.stringify(L, null, 2);
  document.getElementById('dlg').showModal();
};
document.getElementById('btnClose').onclick = ()=>document.getElementById('dlg').close();
document.getElementById('btnCopy').onclick = async ()=>{
  const ta = document.getElementById('json');
  try { await navigator.clipboard.writeText(ta.value); hint('已复制到剪贴板'); }
  catch(e){ ta.select(); document.execCommand('copy'); hint('已复制'); }
};
document.getElementById('btnSave').onclick = ()=>{
  const blob = new Blob([document.getElementById('json').value],
                        {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'puzzle_layout.json';
  a.click();
  hint('已下载 puzzle_layout.json');
};

document.addEventListener('keydown', e=>{
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === '+' || e.key === '=') applyZoom(CELL * 1.2);
  else if (e.key === '-' || e.key === '_') applyZoom(CELL / 1.2);
  else if (e.key === '0') applyZoom(BASE);
  else if (e.key === 'f' || e.key === 'F') zoomFit();
});

window.addEventListener('resize', ()=>{ relayout(); });

// 标题栏显示来源信息 —— 换图后忘了重新生成时，一眼能看出手里这份是旧的
document.getElementById('gen').textContent =
  TILES.length + ' 幅 · 生成于 __GENTIME__';

buildTray(); sync(); relayout();
window.addEventListener('dragover', e=>e.preventDefault());
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="生成拼图工作台网页")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--thumb", type=int, default=260, help="缩略图宽度(px)")
    ap.add_argument("-o", "--out", default=None, help="输出 html 路径")
    ap.add_argument("--open", action="store_true", help="生成后打开浏览器")
    ap.add_argument("--from", dest="src", default=None,
                    help="图源目录（默认用配置里的裁切输出目录）")
    a = ap.parse_args()

    import yaml
    base = os.path.dirname(os.path.abspath(a.config))
    cfgp = os.path.abspath(a.config)
    if a.src:
        src = os.path.abspath(a.src)
    else:
        if not os.path.exists(cfgp):
            sys.exit("找不到 %s，请先复制 config.example.yaml" % a.config)
        cfg = yaml.safe_load(open(cfgp, encoding="utf-8"))
        src = os.path.join(base, cfg["paths"]["crop"])

    if not os.path.isdir(src):
        sys.exit("图源目录不存在: %s\n（先跑 01_crop.py，或用 --from 指定目录）" % src)

    files = sorted(f for f in os.listdir(src)
                   if f.lower().endswith(".png") and f.endswith("_inner.png"))
    if not files:
        files = sorted(f for f in os.listdir(src) if f.lower().endswith((".png", ".jpg")))
    if not files:
        sys.exit("目录里没有图片: %s" % src)

    print("读取 %d 幅缩略图（宽 %d px）..." % (len(files), a.thumb))
    tiles = []
    for i, f in enumerate(files, 1):
        p = os.path.join(src, f)
        thumb, w, h = make_thumb(p, a.thumb)
        label = f[:-len("_inner.png")] if f.endswith("_inner.png") else os.path.splitext(f)[0]
        tiles.append({"name": f, "label": label, "thumb": thumb,
                      "w": w, "h": h})
        if i % 20 == 0 or i == len(files):
            print("   %d/%d" % (i, len(files)))

    import time as _t
    stamp = _t.strftime("%m-%d %H:%M")
    html = HTML.replace("__TILES__", json.dumps(tiles, ensure_ascii=False))
    html = html.replace("__GENTIME__", stamp)
    out = a.out or os.path.join(base, "puzzle.html")

    # 已有旧文件时，报出它装了多少幅 —— 用户常忘记重新生成，
    # 看到"覆盖了旧的 N 幅版本"就知道手里那份该换了。
    prev_n = None
    if os.path.exists(out):
        try:
            import re as _re
            m = _re.search(r"const TILES = (\[.*?\]);",
                           open(out, encoding="utf-8").read(), _re.S)
            if m:
                prev_n = len(json.loads(m.group(1)))
        except Exception:
            pass

    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    if prev_n is not None:
        # 幅数相同也要报 —— 换了一批数量相同但内容不同的图，同样会让
        # 用户拿着旧页面找不着北。
        print("  （已覆盖原有的拼图页面：旧版 %d 幅）" % prev_n)

    size_mb = os.path.getsize(out) / 1024 / 1024
    print()
    print("拼图工作台已生成: %s  (%.2f MB)" % (out, size_mb))
    print("  用浏览器打开它，把左侧缩略图拖到画布上摆成正确位置，")
    print("  然后点『导出布局』，把 JSON 存成 puzzle_layout.json。")
    if a.open:
        webbrowser.open("file:///" + out.replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
