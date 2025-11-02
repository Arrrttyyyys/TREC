#!/usr/bin/env python3
# TREC Inspection Report PDF Generator — overlap-safe version
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
from reportlab.lib.colors import black, white, HexColor
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

    # Discover widgets we care about
    checkbox_pat = re.compile(r"CheckBox1\[(\d+)\]$")
    checkboxes = []
    hdr_fields = []
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

            if ftype == NameObject("/Tx"):  # text field
                # header fields: match by normalized name tail
                nm = normalize(name_str)
                matched = None
                for k in header.keys():
                    if nm.endswith(k):
                        matched = k
                        break
                if matched:
                    hdr_fields.append((pidx, rect, a, matched))
                else:
                    # candidate comment box? filter by geometry + page
                    rc = rect_coords(rect)
                    wpx = rc["right"] - rc["left"]
                    hpx = rc["top"] - rc["bottom"]
                    # Only keep LARGE boxes (avoid tiny inline widgets)
                    # Typical comment boxes are > 300 pts wide and > 50 pts high
                    if wpx >= 300 and hpx >= 50 and pidx in (2,3,4,5):  # pages 3–6 (0-based)
                        comment_fields.append((pidx, rect, a))
            elif ftype == NameObject("/Btn") and "CheckBox1[" in name_str:
                m = checkbox_pat.search(name_str)
                if m:
                    checkboxes.append((pidx, int(m.group(1)), w))

    print(f"   Header fields: {len(hdr_fields)} | comment boxes: {len(comment_fields)} | checkboxes: {len(checkboxes)}")

    overlays = [[] for _ in range(len(writer.pages))]
    overflow = []

    # Fill header fields (and remove widgets)
    for pidx, rect, aref, key in hdr_fields:
        overlays[pidx].append({"rect": tuple(float(x) for x in rect), "text": header[key], "kind": "header"})
        page = writer.pages[pidx]
        ann = page.get("/Annots")
        if ann:
            page[NameObject("/Annots")] = ArrayObject([x for x in ann if x != aref])

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

    # Fill comment boxes (largest boxes only), top→bottom by Y
    comment_fields.sort(key=lambda t: (t[0], -rect_coords(t[1])["top"]))
    max_bind = min(len(items), len(comment_fields))
    for i in range(max_bind):
        it = items[i]
        pidx, rect, aref = comment_fields[i]
        overlays[pidx].append({"rect": tuple(float(x) for x in rect), "text": it.get("text",""), "kind": "comment", "item": it})
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
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        for ov in overlays[pidx]:
            ok, rest = draw_text_in_rect(c, ov["rect"], ov["text"])
            if (not ok) and rest.strip():
                it = ov.get("item", {})
                overflow.append({
                    "section": it.get("section",""),
                    "sectionNumber": it.get("sectionNumber",""),
                    "title": it.get("title",""),
                    "text": rest
                })
        c.showPage(); c.save(); buf.seek(0)
        overlay_reader = PdfReader(buf)
        writer.pages[pidx].merge_page(overlay_reader.pages[0])

    # Anything not bound to a field goes to appendix
    for it in items[max_bind:]:
        overflow.append(it)

    # Appendix: overflow + media
    app_buf = BytesIO()
    c = canvas.Canvas(app_buf, pagesize=letter)
    W, H = letter
    x, y = 60, H - 60

    if overflow:
        c.setFont("Helvetica-Bold", 14)
        c.drawString(x, y, "Additional Information Provided by Inspector")
        y -= 24
        c.setFont(FIXED_FONT, FIXED_SIZE)

        def block(txt: str, width: float, y0: float) -> float:
            tb = BytesIO(); tc = canvas.Canvas(tb, pagesize=letter)
            lines = wrap_text(txt, tc, width)
            for ln in lines:
                if y0 < 60:
                    c.showPage(); c.setFont(FIXED_FONT, FIXED_SIZE)
                    y0 = H - 60
                c.drawString(x, y0, ln)
                y0 -= LINE_HEIGHT
            return y0

        for it in overflow:
            head = " — ".join([s for s in [f"{it.get('sectionNumber','')}. {it.get('section','')}".strip(". "), it.get('title','')] if s])
            if head:
                y = block(head, W - 120, y)
            if it.get("text"):
                y = block(it["text"], W - 120, y)
            y -= LINE_HEIGHT/2

    if media:
        if y < 120:
            c.showPage(); y = H - 60
        c.setFont("Helvetica-Bold", 14); c.drawString(x, y, "Media (in JSON order)")
        y -= 24; c.setFont(FIXED_FONT, FIXED_SIZE)

        col_w = 2.9 * inch
        col_h = 2.1 * inch
        cols = [x, x + col_w + 24]
        col = 0

        for i, m in enumerate(media, start=1):
            kind, url = m.get("kind"), m.get("url","")
            if kind == "photo":
                img = fetch_image(url, max_size=MAX_IMAGE_SIZE)
                if img:
                    iw, ih = getattr(img, "_image", getattr(img, "image", None)).size
                    scale = min(col_w/iw, col_h/ih)
                    rw, rh = iw*scale, ih*scale
                    if y - rh - 18 < 60:
                        c.showPage(); y = H - 60; c.setFont(FIXED_FONT, FIXED_SIZE)
                        c.setFont("Helvetica-Bold",14); c.drawString(x,y,"Media (in JSON order)")
                        y -= 24; c.setFont(FIXED_FONT, FIXED_SIZE); col = 0
                    cx = cols[col]
                    c.setFont("Helvetica-Bold", 10); c.drawString(cx, y, f"M#{i}: photo"); y -= 12
                    c.drawImage(img, cx, y - rh, width=rw, height=rh, preserveAspectRatio=True, mask='auto')
                    if col == 1:
                        y = y - rh - 16
                    col = 1 - col
                    if col == 0:
                        y -= 12
                else:
                    if y < 70:
                        c.showPage(); y = H - 60; c.setFont(FIXED_FONT, FIXED_SIZE)
                        c.setFont("Helvetica-Bold",14); c.drawString(x,y,"Media (in JSON order)")
                        y -= 24; c.setFont(FIXED_FONT, FIXED_SIZE)
                    c.drawString(x, y, f"M#{i}: photo (unavailable)  {url}")
                    y -= LINE_HEIGHT
            else:
                if y < 70:
                    c.showPage(); y = H - 60; c.setFont(FIXED_FONT, FIXED_SIZE)
                    c.setFont("Helvetica-Bold",14); c.drawString(x,y,"Media (in JSON order)")
                    y -= 24; c.setFont(FIXED_FONT, FIXED_SIZE)
                label = f"M#{i}: video"
                c.setFillColor(HexColor("#0645AD")); c.drawString(x, y, label)
                tw = c.stringWidth(label, FIXED_FONT, FIXED_SIZE)
                c.linkURL(url, (x, y - 2, x + tw, y + 10), relative=0)
                c.setFillColor(black)
                y -= LINE_HEIGHT
                # also print the URL (wrapped) so the link is obvious in printouts
                tb = BytesIO(); tc = canvas.Canvas(tb, pagesize=letter)
                for ln in wrap_text(url, tc, (W-120) - (tw + 8)):
                    if y < 60:
                        c.showPage(); y = H - 60; c.setFont(FIXED_FONT, FIXED_SIZE)
                    c.drawString(x + tw + 8, y, ln)
                    y -= LINE_HEIGHT

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
    out_path = Path(os.environ.get("OUT_PATH", here / "TREC_Filled_Output.pdf"))

    print("\n=== TREC Inspection Report PDF Generator (overlap-safe) ===\n")
    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    data = raw.get("inspection", raw)

    fill_trec_form(tpl_path, data, out_path)
    dt = time.time() - t0
    print(f"\n✅ Done: {out_path}\n⏱️ Elapsed: {dt:.2f} seconds\n")


if __name__ == "__main__":
    main()
