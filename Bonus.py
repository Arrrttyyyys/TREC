#!/usr/bin/env python3
import os, json, re, time, html
from pathlib import Path
from io import BytesIO
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import Color, black, white, HexColor
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter
from PIL import Image
import requests

PAGE_SIZE = letter
MARGIN = 54
W, H = PAGE_SIZE
FONT = "Helvetica"
FONT_B = "Helvetica-Bold"
FS = 10.5
LH = FS * 1.35
TITLE_FS = 22
H2_FS = 14
H3_FS = 11.5
TOC_ROW = 16
CARD_PAD = 10
GAP = 10
COLOR_BG = HexColor("#0A0F1F")
COLOR_ACCENT = HexColor("#00C2A8")
COLOR_MUTED = HexColor("#566173")
COLOR_GRID = HexColor("#EEF2F7")
COLOR_I = HexColor("#3BB273")
COLOR_NI = HexColor("#F5A524")
COLOR_NP = HexColor("#9AA5B1")
COLOR_D = HexColor("#E25555")
INLINE_IMG_MAX_H = 2.4 * inch
JPEG_QUALITY = 75
SKIP_LARGE_IMAGES = True
MEDIA_TOKEN_RE = re.compile(r"\[M#(\d+)\]")
COVER_IMAGE_PATH = Path(__file__).parent / "pic1.jpg"
MAX_MEDIA_THREADS = 12
REQUEST_TIMEOUT = (3.0, 5.0)
DEBUG_TIMING = os.environ.get("DEBUG_TIMING", "0") == "1"

def ms_to_iso(ms):
    if isinstance(ms, int):
        return datetime.fromtimestamp(ms/1000.0, tz=timezone.utc).date().isoformat()
    return "Data not found in test data"

def getv(doc: Dict[str, Any], path: str, default="Data not found in test data"):
    cur = doc
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur if cur not in ("", None) else default

def wrap_lines(text: str, c0: canvas.Canvas, max_width: float, fs: float) -> List[str]:
    c0.setFont(FONT, fs)
    out: List[str] = []
    for para in (text or "").split("\n"):
        words = para.split()
        if not words:
            out.append("")
            continue
        cur = ""
        for w in words:
            t = w if not cur else f"{cur} {w}"
            if c0.stringWidth(t, FONT, fs) <= max_width:
                cur = t
            else:
                if cur:
                    out.append(cur)
                cur = w
        if cur:
            out.append(cur)
    return out

def fetch_image(url: str, max_w: int = 1200, max_h: int = 900) -> Optional[ImageReader]:
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        if r.status_code != 200:
            return None
        cl = r.headers.get("content-length")
        if cl and int(cl) > 5_000_000 and SKIP_LARGE_IMAGES:
            return None
        img = Image.open(BytesIO(r.content))
        if img.mode in ("RGBA", "LA", "P"):
            rgb = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            rgb.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = rgb
        img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        buf.seek(0)
        return ImageReader(Image.open(buf))
    except Exception:
        return None

def extract(data: Dict[str, Any]):
    head = {
        "client": str(getv(data, "clientInfo.name")),
        "date": ms_to_iso(getv(data, "schedule.date", None)),
        "address": "",
        "inspector": str(getv(data, "inspector.name")),
        "license": str(getv(data, "inspector.license", "")),
    }
    addr_full = getv(data, "address.fullAddress", "")
    if not addr_full or addr_full == "Data not found in test data":
        parts = [getv(data, "address.street", ""), getv(data, "address.city", ""), getv(data, "address.state", ""), getv(data, "address.zipcode", "")]
        addr_full = " ".join([p for p in parts if p]) or "Data not found in test data"
    head["address"] = addr_full
    items = []
    media = []
    cover = data.get("headerImageUrl")
    if isinstance(cover, str) and cover.strip():
        media.append({"kind": "photo", "url": cover.strip()})
    for section in (data.get("sections") or []):
        sname = section.get("name") or ""
        snum = section.get("sectionNumber") or ""
        for li in (section.get("lineItems") or []):
            status = (li.get("inspectionStatus") or "").upper()
            title = (li.get("title") or li.get("name") or "").strip()
            paragraphs, mrefs = [], []
            for cmt in (li.get("comments") or []):
                text = (cmt.get("commentText") or cmt.get("text") or "").strip()
                if text:
                    paragraphs.append(html.unescape(text))
                for ph in (cmt.get("photos") or []):
                    url = ph if isinstance(ph, str) else (ph.get("url") if isinstance(ph, dict) else None)
                    if url:
                        media.append({"kind": "photo", "url": url})
                        mrefs.append(len(media))
                for vd in (cmt.get("videos") or []):
                    url = vd if isinstance(vd, str) else (vd.get("url") if isinstance(vd, dict) else None)
                    if url:
                        media.append({"kind": "video", "url": url})
                        mrefs.append(len(media))
            body = "\n\n".join(paragraphs).strip()
            if mrefs:
                body = (body + ("\n\n" if body else "") + " ".join(f"[M#{i}]" for i in mrefs)).strip()
            items.append({"section": sname, "sectionNumber": snum, "title": title, "status": status, "text": body})
    return head, items, media

def status_color(code: str) -> Color:
    if code == "D": return COLOR_D
    if code == "NI": return COLOR_NI
    if code == "NP": return COLOR_NP
    return COLOR_I

def build_media_map(media: List[Dict[str, str]]):
    out: Dict[int, Dict[str, Any]] = {}
    if not media:
        return out
    photo_targets: Dict[str, List[int]] = {}
    for i, m in enumerate(media, start=1):
        kind = m.get("kind")
        url = m.get("url", "")
        entry = {"kind": kind, "url": url, "img": None}
        out[i] = entry
        if kind == "photo" and url:
            photo_targets.setdefault(url, []).append(i)
    if not photo_targets:
        return out
    workers = min(MAX_MEDIA_THREADS, len(photo_targets))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(fetch_image, url): url for url in photo_targets}
        for future in as_completed(future_map):
            url = future_map[future]
            try:
                img = future.result()
            except Exception:
                img = None
            for idx in photo_targets[url]:
                out[idx]["img"] = img
    return out

def draw_header(c: canvas.Canvas, client: str, addr: str, date: str, inspector: str):
    c.setFillColor(COLOR_BG); c.rect(0, H-140, W, 140, fill=1, stroke=0)
    c.setFillColor(white); c.setFont(FONT_B, TITLE_FS); c.drawString(MARGIN, H-80, "Home Inspection Report")
    c.setFont(FONT, 12)
    c.drawString(MARGIN, H-110, addr)
    c.setFont(FONT, 10)
    c.drawRightString(W-MARGIN, H-110, f"Inspection Date: {date}")
    c.setFillColor(COLOR_ACCENT); c.setFont(FONT_B, 12); c.drawString(MARGIN, H-128, f"Inspector: {inspector}  |  Client: {client}")
    c.setFillColor(black)

def draw_cover_image(c: canvas.Canvas):
    if not COVER_IMAGE_PATH.exists():
        return
    try:
        with Image.open(COVER_IMAGE_PATH) as raw_img:
            img = raw_img if raw_img.mode in ("RGB", "L") else raw_img.convert("RGB")
            iw, ih = img.size
            if iw == 0 or ih == 0:
                return
            max_w = W - 2 * MARGIN
            top = H - 140 - 24
            available_h = top - MARGIN
            if available_h <= 0 or max_w <= 0:
                return
            scale = min(max_w / iw, available_h / ih, 1.0)
            draw_w, draw_h = iw * scale, ih * scale
            x = MARGIN + (max_w - draw_w) / 2
            y = top - draw_h
            if y < MARGIN:
                y = MARGIN
            c.drawImage(ImageReader(img), x, y, width=draw_w, height=draw_h, preserveAspectRatio=True, mask='auto')
    except Exception:
        return

def footer(c: canvas.Canvas, page_label: str = ""):
    c.setFont(FONT, 9); c.setFillColor(COLOR_MUTED)
    c.drawString(MARGIN, 24, page_label)
    c.drawRightString(W-MARGIN, 24, f"Page {c.getPageNumber()}")
    c.setFillColor(black)

def new_page(c: canvas.Canvas, page_label: str = ""):
    footer(c, page_label); c.showPage()

def draw_exec_summary(c: canvas.Canvas, head, items):
    c.bookmarkPage("exec")
    c.addOutlineEntry("Executive Summary", "exec", level=0, closed=False)
    c.setFont(FONT_B, H2_FS); c.setFillColor(COLOR_BG); c.drawString(MARGIN, H-MARGIN-10, "Executive Summary")
    c.setFillColor(black)
    y = H-MARGIN-10-LH-6
    counts = {"I":0,"NI":0,"NP":0,"D":0}
    for it in items:
        counts[it.get("status","I")] = counts.get(it.get("status","I"),0)+1
    bar_total = max(1, sum(counts.values()))
    bar_w = W - 2*MARGIN
    bar_h = 12
    x0 = MARGIN
    for code in ["D","NI","I","NP"]:
        n = counts.get(code,0)
        wseg = bar_w * (n / bar_total)
        c.setFillColor(status_color(code)); c.rect(x0, y-4, wseg, bar_h, fill=1, stroke=0)
        x0 += wseg
    c.setFillColor(black); c.setFont(FONT, 10)
    y -= 18
    for label, code in [("Deficient", "D"),("Needs Improvement","NI"),("Inspected","I"),("Not Present","NP")]:
        c.setFillColor(status_color(code)); c.rect(MARGIN, y-8, 10, 10, fill=1, stroke=0)
        c.setFillColor(black); c.drawString(MARGIN+16, y-6, f"{label}: {counts.get(code,0)}")
        y -= 14
    y -= 6
    top_flags = [it for it in items if it.get("status") in ("D","NI")]
    c.setFont(FONT_B, H3_FS); c.drawString(MARGIN, y, "Highlights")
    y -= LH
    c.setFont(FONT, FS)
    for it in top_flags[:8]:
        if y < 80: new_page(c, "Executive Summary"); y = H-MARGIN
        c.setFillColor(status_color(it.get("status"))); c.rect(MARGIN, y-10, 6, 6, fill=1, stroke=0)
        c.setFillColor(black); c.drawString(MARGIN+12, y-10, f"{it.get('sectionNumber','')}. {it.get('section','')} — {it.get('title','')}")
        y -= LH
    return

def section_key(it): 
    sn = it.get("sectionNumber","")
    try:
        return (int(sn), it.get("section",""))
    except:
        return (9999, it.get("section",""))

def draw_toc(c: canvas.Canvas, toc_entries: List[Tuple[str,int,str]]):
    c.bookmarkPage("toc")
    c.addOutlineEntry("Table of Contents", "toc", level=0, closed=False)
    c.setFont(FONT_B, H2_FS); c.setFillColor(COLOR_BG); c.drawString(MARGIN, H-MARGIN-10, "Table of Contents")
    c.setFillColor(black)
    y = H-MARGIN-10-LH
    c.setFont(FONT, 11)
    for title, page, dest in toc_entries:
        if y < 80:
            new_page(c, "Table of Contents"); y = H-MARGIN
        text = f"{title}"
        tw = c.stringWidth(text, FONT, 11)
        c.drawString(MARGIN, y, text)
        dots = "." * max(2, int((W - MARGIN*2 - tw - 40) / c.stringWidth(".", FONT, 11)))
        c.drawString(MARGIN+tw+4, y, dots)
        pn = str(page)
        c.drawRightString(W-MARGIN, y, pn)
        c.linkAbsolute("", dest, (MARGIN, y-2, MARGIN+tw, y+10))
        y -= TOC_ROW

def draw_inline(c: canvas.Canvas, text: str, x: float, y: float, width: float, media_map: Dict[int, Dict[str, Any]], render_media: bool = True) -> float:
    def draw_wrapped(chunk: str, y0: float) -> float:
        if not chunk: return y0
        for ln in wrap_lines(chunk, c, width, FS):
            if y0 < 72:
                new_page(c, cur_label[0]); y0 = H - MARGIN
            c.drawString(x, y0, ln); y0 -= LH
        return y0
    pos = 0
    for m in MEDIA_TOKEN_RE.finditer(text or ""):
        pre = text[pos:m.start()]
        y = draw_wrapped(pre, y)
        idx = int(m.group(1))
        meta = media_map.get(idx)
        if y < 88:
            new_page(c, cur_label[0]); y = H - MARGIN
        if not meta:
            c.setFont(FONT_B, 10); c.drawString(x, y, f"M#{idx}: (missing)"); y -= LH; c.setFont(FONT, FS)
        else:
            if meta.get("kind") == "photo" and meta.get("img"):
                img = meta["img"]
                try:
                    iw, ih = getattr(img, "_image", getattr(img, "image", None)).size
                except Exception:
                    iw, ih = (800, 600)
                scale = min(width/iw, INLINE_IMG_MAX_H/ih)
                rw, rh = iw*scale, ih*scale
                if y - rh - 16 < 72:
                    new_page(c, cur_label[0]); y = H - MARGIN
                c.setFont(FONT_B, 10); c.drawString(x, y, f"M#{idx}: photo"); y -= 12
                if render_media:
                    c.drawImage(img, x, y - rh, width=rw, height=rh, preserveAspectRatio=True, mask='auto')
                y = y - rh - 8; c.setFont(FONT, FS)
            elif meta.get("kind") == "video":
                label = f"Video M#{idx}"
                c.setFont(FONT_B, 10); c.setFillColor(HexColor("#0645AD")); c.drawString(x, y, label)
                tw = c.stringWidth(label, FONT_B, 10)
                url = meta.get("url") or ""
                if url:
                    c.linkURL(url, (x, y-2, x+tw, y+10), relative=0)
                c.setFillColor(black); y -= LH; c.setFont(FONT, FS)
            else:
                c.setFont(FONT_B, 10); c.drawString(x, y, f"M#{idx}: (unavailable)"); y -= LH; c.setFont(FONT, FS)
        pos = m.end()
    tail = (text or "")[pos:]
    y = draw_wrapped(tail, y)
    return y

def draw_item_card(c: canvas.Canvas, it: Dict[str, Any], x: float, y: float, width: float, media_map, render_media: bool = True) -> float:
    title = it.get("title","")
    status = it.get("status","I")
    txt = it.get("text","")
    card_w = width
    title_h = 16
    band_w = 6
    lines = wrap_lines(title, c, card_w - band_w - 2*CARD_PAD, 11.5)
    content_h = LH * max(1, len(lines)) + 10
    y0 = y
    if y - (content_h + 10) < 72:
        new_page(c, cur_label[0]); y = H - MARGIN; y0 = y
    c.setFillColor(white); c.rect(x, y - (content_h + 10), card_w, content_h + 10, fill=1, stroke=0)
    c.setFillColor(status_color(status)); c.rect(x, y - (content_h + 10), band_w, content_h + 10, fill=1, stroke=0)
    c.setStrokeColor(COLOR_GRID); c.rect(x, y - (content_h + 10), card_w, content_h + 10, fill=0, stroke=1)
    c.setFillColor(black)
    c.setFont(FONT_B, 11.5)
    ty = y - CARD_PAD - 2
    c.drawString(x + band_w + CARD_PAD, ty, title)
    c.setFont(FONT, FS)
    ty -= LH
    if txt:
        ty = draw_inline(c, txt, x + band_w + CARD_PAD, ty, card_w - band_w - 2*CARD_PAD, media_map, render_media=render_media)
    return ty - GAP

def render_report(data: Dict[str, Any], out_path: Path):
    t_start = time.perf_counter()
    head, items, media = extract(data)
    media_map = build_media_map(media)
    t_after_media = time.perf_counter()
    groups: Dict[str, List[Dict[str,Any]]] = {}
    order_keys: List[str] = []
    for it in sorted(items, key=section_key):
        k = f"{it.get('sectionNumber','')}. {it.get('section','')}".strip(". ")
        if k not in groups:
            groups[k] = []
            order_keys.append(k)
        groups[k].append(it)

    section_pages: Dict[str,int] = {}
    toc_page_number = 0

    def doc(pass_collect: bool, render_media: bool) -> BytesIO:
        nonlocal toc_page_number
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=PAGE_SIZE)
        draw_header(c, head["client"], head["address"], head["date"], head["inspector"])
        draw_cover_image(c)
        c.bookmarkPage("cover")
        c.addOutlineEntry("Cover", "cover", level=0, closed=False)
        footer(c, "Cover"); c.showPage()

        c.setFont(FONT_B, H2_FS); c.setFillColor(COLOR_BG); c.drawString(MARGIN, H-MARGIN-10, "Executive Summary")
        c.setFillColor(black)
        draw_exec_summary(c, head, items)
        footer(c, "Executive Summary"); c.showPage()

        toc_start_page = c.getPageNumber()
        c.setFont(FONT_B, H2_FS); c.setFillColor(COLOR_BG); c.drawString(MARGIN, H-MARGIN-10, "Table of Contents")
        c.setFillColor(black)
        footer(c, "Table of Contents"); c.showPage()
        if pass_collect:
            toc_page_number = toc_start_page

        for key in order_keys:
            dest = f"sec::{key}"
            c.bookmarkPage(dest)
            c.addOutlineEntry(key, dest, level=0, closed=False)
            if pass_collect and key not in section_pages:
                section_pages[key] = c.getPageNumber()
            c.setFont(FONT_B, H2_FS); c.setFillColor(COLOR_BG); c.drawString(MARGIN, H-MARGIN-10, key)
            c.setFillColor(black)
            y = H - MARGIN - 10 - LH
            c.setFont(FONT, 10); c.setFillColor(COLOR_MUTED)
            c.drawString(MARGIN, y, "Status key: "); 
            xk = MARGIN + c.stringWidth("Status key: ", FONT, 10) + 6
            for lab, code in [("D","D"),("NI","NI"),("I","I"),("NP","NP")]:
                c.setFillColor(status_color(code)); c.rect(xk, y-8, 10, 10, fill=1, stroke=0)
                c.setFillColor(black); c.drawString(xk+14, y-6, lab)
                xk += 44
            c.setFillColor(black)
            y -= LH + 4
            global cur_label
            cur_label = (key,)
            for it in groups[key]:
                y = draw_item_card(c, it, MARGIN, y, W - 2*MARGIN, media_map, render_media=render_media)
                if y < 100:
                    new_page(c, key); y = H - MARGIN
            footer(c, key); c.showPage()
        buf.seek(0)
        c.save()
        buf.seek(0)
        return buf

    first_pass_buf = doc(True, render_media=True)
    t_after_first_pass = time.perf_counter()
    toc_entries = [(k, section_pages.get(k, 1), f"sec::{k}") for k in order_keys]

    reader = PdfReader(first_pass_buf)
    toc_page_index = max(0, toc_page_number - 1) if toc_entries else 0
    link_rects: List[Tuple[tuple[float, float, float, float], int]] = []

    if toc_entries:
        buf_overlay = BytesIO()
        overlay = canvas.Canvas(buf_overlay, pagesize=PAGE_SIZE)
        overlay.setFillColor(black)
        overlay.setFont(FONT, 11)
        y = H - MARGIN - 10 - LH
        for title, page_no, dest in toc_entries:
            if y < 80:
                buf_overlay = None
                break
            text = f"{title}"
            tw = overlay.stringWidth(text, FONT, 11)
            overlay.drawString(MARGIN, y, text)
            dots_count = max(2, int((W - MARGIN*2 - tw - 40) / overlay.stringWidth(".", FONT, 11)))
            overlay.drawString(MARGIN + tw + 4, y, "." * dots_count)
            overlay.drawRightString(W - MARGIN, y, str(page_no))
            link_rects.append(((MARGIN, y-2, MARGIN + tw, y + 10), page_no - 1))
            y -= TOC_ROW
        if buf_overlay is None:
            reader = PdfReader(doc(False, render_media=True))
            link_rects = []
        else:
            overlay.save(); buf_overlay.seek(0)
            overlay_reader = PdfReader(buf_overlay)
            target_page = reader.pages[toc_page_index]
            target_page.merge_page(overlay_reader.pages[0])
            from pypdf.generic import NameObject, ArrayObject
            from pypdf.annotations import Link
            annot_key = NameObject("/Annots")
            existing_annots = target_page.get(annot_key)
            if existing_annots is None:
                annots_array = ArrayObject()
            else:
                annots_array = ArrayObject(existing_annots)
            for rect, target_idx in link_rects:
                annots_array.append(Link(rect=rect, target_page_index=target_idx))
            target_page[annot_key] = annots_array

    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    root = writer._root_object
    acro = root.get("/AcroForm")
    if acro is not None:
        from pypdf.generic import NameObject, BooleanObject
        acro.update({NameObject("/NeedAppearances"): BooleanObject(False)})
    with open(out_path, "wb") as f:
        writer.write(f)
    t_end = time.perf_counter()
    if DEBUG_TIMING:
        print(f"[timing] media_map={t_after_media - t_start:.2f}s, render={t_after_first_pass - t_after_media:.2f}s, total={t_end - t_after_media:.2f}s")


def main():
    t0 = time.time()
    here = Path(__file__).parent
    json_path = Path(os.environ.get("JSON_PATH", here / "inspection.json"))
    out_path = Path(os.environ.get("OUT_PATH", here / "bonus_pdf.pdf"))
    with open(json_path, "r", encoding="utf-8") as fp:
        root = json.load(fp)
    data = root.get("inspection", root)
    render_report(data, out_path)
    dt = time.time() - t0
    print(f"✅ Wrote: {out_path}  ⏱ {dt:.2f}s")

if __name__ == "__main__":
    main()
