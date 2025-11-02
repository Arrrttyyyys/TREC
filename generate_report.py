#!/usr/bin/env python3
# TREC Inspection Report PDF Generator — header-first overlay + overlap-safe body with INLINE MEDIA
import os, json, re, time, html
from pathlib import Path
from io import BytesIO
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, BooleanObject, ArrayObject

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import black, white, HexColor, Color
from reportlab.lib.utils import ImageReader
from PIL import Image
import requests

# =============== Config ===============
FIXED_FONT = "Helvetica"
FIXED_SIZE = 10.0
LINE_HEIGHT = FIXED_SIZE * 1.2
LEFT_PAD = 6
RIGHT_PAD = 6
TOP_PAD = 6
BOT_PAD = 6

MAX_IMAGE_SIZE = (800, 600)
JPEG_QUALITY = 75
SKIP_LARGE_IMAGES = True  # skip >5MB

# Inline image sizing in the appendix text flow
INLINE_IMG_MAX_H = 2.4 * inch

# If you want the raw video URLs to also be printed (in addition to the clickable label),
# set environment variable SHOW_VIDEO_URLS=1 when running the script.
SHOW_VIDEO_URLS = os.environ.get("SHOW_VIDEO_URLS", "0") == "1"

I, NI, NP, D = "I", "NI", "NP", "D"


# =============== Utils ===============
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


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def rect_coords(rect) -> Dict[str, float]:
    return {
        "left": float(min(rect[0], rect[2])),
        "right": float(max(rect[0], rect[2])),
        "bottom": float(min(rect[1], rect[3])),
        "top": float(max(rect[1], rect[3])),
    }


# =============== Data extraction ===============
def extract_header_data(data: Dict[str, Any]) -> Dict[str, str]:
    addr_full = getv(data, "address.fullAddress", "")
    if not addr_full or addr_full == "Data not found in test data":
        parts = [
            getv(data, "address.street", ""),
            getv(data, "address.city", ""),
            getv(data, "address.state", ""),
            getv(data, "address.zipcode", ""),
        ]
        addr_full = " ".join([p for p in parts if p])

    return {
        # these keys match the normalized tail of the PDF header field names
        "nameofclient": str(getv(data, "clientInfo.name")),
        "dateofinspection": ms_to_iso(getv(data, "schedule.date", None)),
        "addressofinspectedproperty": str(addr_full or "Data not found in test data"),
        "nameofinspector": str(getv(data, "inspector.name")),
        "treclicens": str(getv(data, "inspector.license", "")),
        "nameofspnsorifapplicable": "",
        "treclicens_2": "",
    }


def extract_items_and_media(data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    items, media = [], []

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

            items.append({
                "section": sname,
                "sectionNumber": snum,
                "title": title,
                "status": status,
                "text": body,
            })

    return items, media


# =============== Layout helpers ===============
def wrap_text(text: str, c0: canvas.Canvas, max_width: float) -> List[str]:
    c0.setFont(FIXED_FONT, FIXED_SIZE)
    lines: List[str] = []
    for para in (text or "").split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for w in words:
            test = w if not cur else f"{cur} {w}"
            if c0.stringWidth(test, FIXED_FONT, FIXED_SIZE) <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    return lines


def draw_text_in_rect(c: canvas.Canvas, rect, text: str) -> Tuple[bool, str]:
    rc = rect_coords(rect)
    left = rc["left"] + LEFT_PAD
    right = rc["right"] - RIGHT_PAD
    bottom = rc["bottom"] + BOT_PAD
    top = rc["top"] - TOP_PAD

    max_w = max(0, right - left)
    max_h = max(0, top - bottom)

    # white out the area so nothing overlaps/bleeds through
    c.setFillColor(white)
    c.rect(rc["left"], rc["bottom"], rc["right"]-rc["left"], rc["top"]-rc["bottom"], fill=1, stroke=0)
    c.setFillColor(black)

    tb = BytesIO()
    tc = canvas.Canvas(tb, pagesize=letter)
    lines = wrap_text(text, tc, max_w)

    capacity = int(max_h // LINE_HEIGHT)
    c.setFont(FIXED_FONT, FIXED_SIZE)
    if capacity <= 0:
        return False, text

    if len(lines) <= capacity:
        y = top - LINE_HEIGHT
        for line in lines:
            c.drawString(left, y, line)
            y -= LINE_HEIGHT
        return True, ""
    else:
        # Fill exactly what fits; remainder goes to appendix (no "continued" note)
        y = top - LINE_HEIGHT
        for line in lines[:capacity]:
            c.drawString(left, y, line)
            y -= LINE_HEIGHT
        remainder = "\n".join(lines[capacity:])
        return False, remainder


def fetch_image(url: str, max_size=(800, 600)) -> Optional[ImageReader]:
    try:
        r = requests.get(url, timeout=8, stream=True)
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
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        buf.seek(0)
        return ImageReader(Image.open(buf))
    except Exception:
        return None


# =============== Header-only overlay (does NOT modify widgets) ===============
def _rect_tuple(rect):
    x1, y1, x2, y2 = [float(v) for v in rect]
    left, right = min(x1, x2), max(x1, x2)
    bottom, top = min(y1, y2), max(y1, y2)
    return (left, bottom, right, top)


def _group_by_rows(rects, y_tol=8.0):
    rows = []
    centers = []
    for r in rects:
        _, b, _, t = r
        yc = 0.5 * (b + t)
        placed = False
        for i, (row, cy) in enumerate(zip(rows, centers)):
            if abs(yc - cy) <= y_tol:
                row.append(r)
                centers[i] = (cy * len(row) + yc) / (len(row) + 1e-9)
                placed = True
                break
        if not placed:
            rows.append([r])
            centers.append(yc)
    rows = [sorted(row, key=lambda R: R[0]) for row in rows]
    rows.sort(key=lambda row: -0.5 * (row[0][1] + row[0][3]))
    return rows


def _draw_shrink_to_fit(c, rect, text, fixed_size=11.0, min_size=8.0, pad=3.0):
    left, bottom, right, top = rect
    text = html.unescape(text or "")
    available = max(1.0, right - left - 2 * pad)
    size = fixed_size
    while size >= min_size:
        w = c.stringWidth(text, FIXED_FONT, size)
        if w <= available:
            break
        size -= 0.5
    c.setFont(FIXED_FONT, size)
    x = left + pad
    y = top - 0.65 * (top - bottom)
    c.drawString(x, y, text)


def header_values_list(data: Dict[str, Any]) -> List[str]:
    addr = getv(data, "address.fullAddress", "")
    if not addr or addr == "Data not found in test data":
        parts = [
            getv(data, "address.street", ""),
            getv(data, "address.city", ""),
            getv(data, "address.state", ""),
            getv(data, "address.zipcode", ""),
        ]
        addr = " ".join([p for p in parts if p]) or "Data not found in test data"

    return [
        str(getv(data, "clientInfo.name")),                 # Name of Client
        ms_to_iso(getv(data, "schedule.date", None)),       # Date of Inspection
        str(addr),                                          # Address of Inspected Property
        str(getv(data, "inspector.name")),                  # Name of Inspector
        str(getv(data, "inspector.license", "")),           # TREC License #
        "",                                                 # Name of Sponsor (if applicable)
        "",                                                 # TREC License # (sponsor)
    ]


def overlay_fill_header_page1(writer: PdfWriter, data: Dict[str, Any]) -> None:
    """
    Draws the page-1 header values ON TOP of the existing widgets (does not modify /Annots).
    """
    if not writer.pages:
        return
    page0 = writer.pages[0]
    annots = page0.get("/Annots") or []

    rects = []
    for a in annots:
        w = a.get_object()
        if w.get("/FT") == NameObject("/Tx"):
            rect = w.get("/Rect")
            if isinstance(rect, ArrayObject) and len(rect) == 4:
                r = _rect_tuple(rect)
                top = float(page0.mediabox.top)
                bottom = float(page0.mediabox.bottom)
                if r[3] > top - (top - bottom) * 0.25:
                    rects.append(r)

    if not rects:
        return

    rows = _group_by_rows(rects, y_tol=8.0)
    ordered_rects = [r for row in rows for r in row]

    values = header_values_list(data)
    n = min(len(values), len(ordered_rects))

    pw = float(page0.mediabox.width)
    ph = float(page0.mediabox.height)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(pw, ph))
    for i in range(n):
        _draw_shrink_to_fit(c, ordered_rects[i], values[i], fixed_size=11.0, min_size=8.0, pad=3.0)
    c.showPage()
    c.save()
    buf.seek(0)

    overlay_reader = PdfReader(buf)
    page0.merge_page(overlay_reader.pages[0])

    root = writer._root_object
    acro = root.get("/AcroForm")
    if acro is not None:
        acro.update({NameObject("/NeedAppearances"): BooleanObject(False)})


# =============== Inline-media helpers ===============
MEDIA_TOKEN_RE = re.compile(r"\[M#(\d+)\]")

def build_media_map(media: List[Dict[str, str]]) -> Dict[int, Dict[str, Any]]:
    """
    Returns {index -> {'kind': 'photo'|'video', 'url': str, 'img': ImageReader|None}}
    Index is 1-based (M#1 ...), matching how tokens are created.
    Photos get pre-fetched; videos keep url only.
    """
    out: Dict[int, Dict[str, Any]] = {}
    for i, m in enumerate(media, start=1):
        kind = m.get("kind")
        url = m.get("url", "")
        entry = {"kind": kind, "url": url, "img": None}
        if kind == "photo":
            entry["img"] = fetch_image(url, max_size=MAX_IMAGE_SIZE)
        out[i] = entry
    return out


def draw_inline_richblock(
    c: canvas.Canvas,
    text: str,
    width: float,
    x: float,
    y: float,
    page_w: float,
    page_h: float,
    media_map: Dict[int, Dict[str, Any]],
) -> float:
    """
    Draw a paragraph that may contain [M#N] tokens, preserving exact order.
    - Text between tokens is wrapped to 'width'.
    - Token M#N:
        * photo & downloadable -> draw inline image (max height INLINE_IMG_MAX_H)
        * photo but not downloadable -> short 'photo (unavailable)' line
        * video -> clickable 'M#N: video' label only (no raw URL unless SHOW_VIDEO_URLS=1)
    Returns updated y.
    """
    def draw_wrapped(chunk: str, y0: float) -> float:
        if not chunk:
            return y0
        c.setFont(FIXED_FONT, FIXED_SIZE)
        tb = BytesIO(); tc = canvas.Canvas(tb, pagesize=(page_w, page_h))
        for ln in wrap_text(chunk, tc, width):
            if y0 < 60:
                c.showPage(); c.setFont(FIXED_FONT, FIXED_SIZE)
                y0 = page_h - 60
            c.drawString(x, y0, ln)
            y0 -= LINE_HEIGHT
        return y0

    pos = 0
    for m in MEDIA_TOKEN_RE.finditer(text):
        pre = text[pos:m.start()]
        y = draw_wrapped(pre, y)

        idx = int(m.group(1))
        meta = media_map.get(idx)

        if y < 70:
            c.showPage(); c.setFont(FIXED_FONT, FIXED_SIZE)
            y = page_h - 60

        if not meta:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(x, y, f"M#{idx}: (missing)")
            y -= LINE_HEIGHT
            c.setFont(FIXED_FONT, FIXED_SIZE)
        else:
            kind = meta.get("kind")
            if kind == "photo" and meta.get("img"):
                img: ImageReader = meta["img"]
                try:
                    iw, ih = getattr(img, "_image", getattr(img, "image", None)).size
                except Exception:
                    iw, ih = (800, 600)
                scale = min(width / iw, INLINE_IMG_MAX_H / ih)
                rw, rh = iw * scale, ih * scale

                if y - rh - 16 < 60:
                    c.showPage(); c.setFont(FIXED_FONT, FIXED_SIZE)
                    y = page_h - 60

                c.setFont("Helvetica-Bold", 10)
                c.drawString(x, y, f"M#{idx}: photo")
                y -= 12
                c.drawImage(img, x, y - rh, width=rw, height=rh,
                            preserveAspectRatio=True, mask='auto')
                y = y - rh - 8
                c.setFont(FIXED_FONT, FIXED_SIZE)

            elif kind == "video":
                label = f"M#{idx}: video"
                url = meta.get("url") or ""

                if y < 70:
                    c.showPage(); c.setFont(FIXED_FONT, FIXED_SIZE)
                    y = page_h - 60

                c.setFont("Helvetica-Bold", 10)
                c.setFillColor(HexColor("#0645AD"))
                c.drawString(x, y, label)
                tw = c.stringWidth(label, "Helvetica-Bold", 10)
                if url:
                    c.linkURL(url, (x, y - 2, x + tw, y + 10), relative=0)
                c.setFillColor(black)
                y -= LINE_HEIGHT

                # Only print the raw URL if explicitly requested
                if SHOW_VIDEO_URLS and url:
                    tb = BytesIO(); tc = canvas.Canvas(tb, pagesize=(page_w, page_h))
                    for ln in wrap_text(url, tc, width):
                        if y < 60:
                            c.showPage(); c.setFont(FIXED_FONT, FIXED_SIZE)
                            y = page_h - 60
                        c.drawString(x, y, ln)
                        y -= LINE_HEIGHT

                c.setFont(FIXED_FONT, FIXED_SIZE)

            else:
                c.setFont("Helvetica-Bold", 10)
                c.drawString(x, y, f"M#{idx}: photo (unavailable)")
                y -= LINE_HEIGHT
                c.setFont(FIXED_FONT, FIXED_SIZE)

        pos = m.end()

    tail = text[pos:]
    y = draw_wrapped(tail, y)
    return y


# =============== Main PDF fill ===============
def fill_trec_form(template_path: Path, data: Dict[str, Any], output_path: Path):
    print(f"📄 Template: {template_path}")
    reader = PdfReader(str(template_path))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    print("📊 Parsing JSON ...")
    header = extract_header_data(data)
    items, media = extract_items_and_media(data)
    print(f"   Items: {len(items)}, media: {len(media)}")

    # --- Phase 1: fill ONLY the page-1 header (overlay; leaves widgets untouched) ---
    overlay_fill_header_page1(writer, data)

    # --- Phase 2: proceed with original overlap-safe filling for the rest ---
    checkbox_pat = re.compile(r"CheckBox1\[(\d+)\]$")
    checkboxes = []
    comment_fields = []

    for pidx, page in enumerate(writer.pages):
        annots = page.get("/Annots") or []
        for a in annots:
            w = a.get_object()
            name = w.get("/T")
            if not name:
                continue
            name_str = str(name)
            ftype = w.get("/FT")
            rect = w.get("/Rect")
            if not isinstance(rect, ArrayObject):
                continue

            if ftype == NameObject("/Tx"):
                # Skip header band on page 1 entirely (already drawn by overlay)
                if pidx == 0:
                    rc = rect_coords(rect)
                    top = float(page.mediabox.top); bottom = float(page.mediabox.bottom)
                    if rc["top"] > top - (top - bottom) * 0.25:
                        continue

                # candidate comment box? filter by geometry + page
                rc = rect_coords(rect)
                wpx = rc["right"] - rc["left"]
                hpx = rc["top"] - rc["bottom"]
                if wpx >= 300 and hpx >= 50 and pidx in (2, 3, 4, 5):  # pages 3–6 (0-based)
                    comment_fields.append((pidx, rect, a))

            elif ftype == NameObject("/Btn") and "CheckBox1[" in name_str:
                m = checkbox_pat.search(name_str)
                if m:
                    checkboxes.append((pidx, int(m.group(1)), w))

    print(f"   Comment boxes: {len(comment_fields)} | checkboxes: {len(checkboxes)}")

    overlays = [[] for _ in range(len(writer.pages))]
    overflow: List[Dict[str, str]] = []

    # Set checkboxes in groups of 4 (I, NI, NP, D) in the order they appear
    checkboxes.sort(key=lambda t: (t[0], t[1]))
    order = [I, NI, NP, D]
    idx = 0
    for it in items:
        if idx + 4 > len(checkboxes):
            break
        grp = checkboxes[idx:idx+4]
        for j, code in enumerate(order):
            w = grp[j][2]
            ap = w.get("/AP") or {}
            normal = ap.get("/N") or {}
            on_name = None
            for k in normal.keys():
                if k != NameObject("/Off"):
                    on_name = k
                    break
            if (it.get("status") or "") == code and on_name:
                w.update({NameObject("/V"): on_name, NameObject("/AS"): on_name})
            else:
                w.update({NameObject("/V"): NameObject("/Off"), NameObject("/AS"): NameObject("/Off")})
        idx += 4

    # Bind comments to the largest boxes, top→bottom by Y
    comment_fields.sort(key=lambda t: (t[0], -rect_coords(t[1])["top"]))
    max_bind = min(len(items), len(comment_fields))
    for i in range(max_bind):
        it = items[i]
        pidx, rect, aref = comment_fields[i]
        overlays[pidx].append({"rect": tuple(float(x) for x in rect), "text": it.get("text", ""), "kind": "comment", "item": it})
        page = writer.pages[pidx]
        ann = page.get("/Annots")
        if ann:
            page[NameObject("/Annots")] = ArrayObject([x for x in ann if x != aref])

    # Remove any remaining /Tx widgets so nothing scrolls
    for page in writer.pages:
        ann = page.get("/Annots")
        if not ann:
            continue
        keep = ArrayObject()
        for a in ann:
            w = a.get_object()
            if w.get("/FT") != NameObject("/Tx"):
                keep.append(a)
        if len(keep):
            page[NameObject("/Annots")] = keep
        else:
            try:
                del page[NameObject("/Annots")]
            except KeyError:
                pass

    # Render overlays (with white background under text)
    for pidx in range(len(writer.pages)):
        if not overlays[pidx]:
            continue
        pw = float(writer.pages[pidx].mediabox.width)
        ph = float(writer.pages[pidx].mediabox.height)
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=(pw, ph))
        for ov in overlays[pidx]:
            ok, rest = draw_text_in_rect(c, ov["rect"], ov["text"])
            if (not ok) and rest.strip():
                it = ov.get("item", {})
                overflow.append({
                    "section": it.get("section", ""),
                    "sectionNumber": it.get("sectionNumber", ""),
                    "title": it.get("title", ""),
                    "text": rest
                })
        c.showPage(); c.save(); buf.seek(0)
        overlay_reader = PdfReader(buf)
        writer.pages[pidx].merge_page(overlay_reader.pages[0])

    # Anything not bound to a field goes to appendix
    for it in items[max_bind:]:
        overflow.append(it)

    # -------- Appendix: overflow with INLINE MEDIA --------
    app_buf = BytesIO()
    pw0 = float(writer.pages[0].mediabox.width)
    ph0 = float(writer.pages[0].mediabox.height)
    c = canvas.Canvas(app_buf, pagesize=(pw0, ph0))
    W, H = pw0, ph0
    x, y = 60, H - 60
    text_width = W - 120

    media_map = build_media_map(media)

    if overflow:
        c.setFont("Helvetica-Bold", 14)
        c.drawString(x, y, "Additional Information Provided by Inspector")
        y -= 24
        c.setFont(FIXED_FONT, FIXED_SIZE)

        def rich_block(txt: str, width: float, y0: float) -> float:
            paras = (txt or "").split("\n")
            for pi, para in enumerate(paras):
                if para.strip() == "":
                    if y0 < 60:
                        c.showPage(); c.setFont(FIXED_FONT, FIXED_SIZE)
                        y0 = H - 60
                    y0 -= LINE_HEIGHT
                    continue
                y0 = draw_inline_richblock(c, para, width, x, y0, W, H, media_map)
            return y0

        for it in overflow:
            head = " — ".join([s for s in [f"{it.get('sectionNumber','')}. {it.get('section','')}".strip(". "), it.get('title','')] if s])
            if head:
                c.setFont("Helvetica-Bold", 11)
                y = draw_inline_richblock(c, head, text_width, x, y, W, H, media_map)
                c.setFont(FIXED_FONT, FIXED_SIZE)
            if it.get("text"):
                y = rich_block(it["text"], text_width, y)
            y -= LINE_HEIGHT/2

    c.showPage(); c.save(); app_buf.seek(0)
    app_reader = PdfReader(app_buf)
    for pg in app_reader.pages:
        writer.add_page(pg)

    # Make sure form appearances aren’t required
    root = writer._root_object
    acro = root.get("/AcroForm")
    if acro is not None:
        acro.update({NameObject("/NeedAppearances"): BooleanObject(False)})

    print(f"💾 Writing: {output_path}")
    with open(output_path, "wb") as f:
        writer.write(f)


# =============== CLI ===============
def main():
    t0 = time.time()
    here = Path(__file__).parent
    json_path = Path(os.environ.get("JSON_PATH", here / "inspection.json"))
    tpl_path = Path(os.environ.get("TREC_TEMPLATE", here / "TREC_Template_Blank.pdf"))
    out_path = Path(os.environ.get("OUT_PATH", here / "output_pdf.pdf"))


    print("\n=== TREC Inspection Report PDF Generator (header-first, overlap-safe, inline media) ===\n")
    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    data = raw.get("inspection", raw)

    fill_trec_form(tpl_path, data, out_path)
    dt = time.time() - t0
    print(f"\n✅ Done: {out_path}\n⏱️ Elapsed: {dt:.2f} seconds\n")


if __name__ == "__main__":
    main()
