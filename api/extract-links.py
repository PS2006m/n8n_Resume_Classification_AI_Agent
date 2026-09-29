"""
POST /extract-links

Accepts a PDF and returns every hyperlink in it:
  - real embedded link annotations (/Annots -> /A -> /URI), which is where the
    LinkedIn / GitHub / portfolio URLs actually live when the visible text is
    just the word "LinkedIn"
  - plus any bare URLs written out in the page text

Accepts the body in three shapes so it works no matter how n8n is configured:
  1. raw binary body  (n8n: Send Body = ON, Body Content Type = "n8n Binary File",
     Input Data Field Name = "resume")   <-- what the current workflow sends
  2. multipart/form-data with a file field (default name "resume")
  3. JSON { "data": "<base64>" } or { "resume": "<base64>" }

Response:
{
  "links": ["https://linkedin.com/in/...", "https://github.com/..."],
  "link_count": 2,
  "annotations": [{"page": 1, "url": "...", "text": "LinkedIn"}, ...],
  "text_urls": [...]
}
"""

import base64
import io
import json
import re
from http.server import BaseHTTPRequestHandler

from pypdf import PdfReader

MAX_BYTES = 15 * 1024 * 1024  # guard; Vercel itself caps request bodies ~4.5 MB

URL_RE = re.compile(
    r"""(?xi)
    \b(
        (?:https?://|www\.)[^\s<>"')\]},]+
        |
        (?:linkedin\.com|github\.com)/[^\s<>"')\]},]+
    )
    """
)

TRAILING_JUNK = ".,;:!?)]}>'\"\u2019\u201d"


def _clean(url: str) -> str:
    url = url.strip().rstrip(TRAILING_JUNK)
    if url.lower().startswith("www."):
        url = "https://" + url
    elif not url.lower().startswith(("http://", "https://", "mailto:")):
        url = "https://" + url
    return url


def _rect(obj):
    try:
        return [float(x) for x in obj]
    except Exception:
        return None


def _text_near(page, rect):
    """Best-effort: the visible label sitting on top of a link annotation."""
    if not rect:
        return None
    x0, y0, x1, y1 = min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3])
    found = []

    def visitor(text, cm, tm, font_dict, font_size):
        if not text or not text.strip():
            return
        x, y = tm[4], tm[5]
        if x0 - 2 <= x <= x1 + 2 and y0 - 1 <= y <= y1 - 4:
            found.append(text.strip())

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return None
    label = " ".join(found).strip()
    return label or None


def extract(pdf_bytes: bytes) -> dict:
    reader = PdfReader(io.BytesIO(pdf_bytes))

    annotations = []
    for page_no, page in enumerate(reader.pages, start=1):
        annots = page.get("/Annots")
        if not annots:
            continue
        try:
            annots = annots.get_object()
        except Exception:
            pass
        for ref in annots:
            try:
                annot = ref.get_object()
            except Exception:
                continue
            if annot.get("/Subtype") != "/Link":
                continue
            action = annot.get("/A")
            if action is None:
                continue
            try:
                action = action.get_object()
            except Exception:
                pass
            uri = action.get("/URI")
            if not uri:
                continue
            rect = _rect(annot.get("/Rect") or [])
            annotations.append(
                {
                    "page": page_no,
                    "url": _clean(str(uri)),
                    "text": _text_near(page, rect),
                }
            )

    full_text = ""
    for page in reader.pages:
        try:
            full_text += (page.extract_text() or "") + "\n"
        except Exception:
            pass

    text_urls = [_clean(m.group(1)) for m in URL_RE.finditer(full_text)]

    seen, links = set(), []
    for url in [a["url"] for a in annotations] + text_urls:
        key = url.rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            links.append(url)

    return {
        "links": links,
        "link_count": len(links),
        "annotations": annotations,
        "text_urls": text_urls,
        "pages": len(reader.pages),
    }


# --------------------------------------------------------------------------
# body parsing
# --------------------------------------------------------------------------

def _from_multipart(body: bytes, content_type: str):
    m = re.search(r'boundary="?([^";]+)"?', content_type, re.I)
    if not m:
        return None
    boundary = ("--" + m.group(1)).encode()
    for part in body.split(boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, _, data = part.partition(b"\r\n\r\n")
        if b"filename=" not in head.lower():
            continue
        data = data.rstrip(b"\r\n").rstrip(b"--").rstrip(b"\r\n")
        if data[:4] == b"%PDF" or data:
            return data
    return None


def get_pdf_bytes(body: bytes, content_type: str):
    if not body:
        return None, "empty request body"

    if body[:4] == b"%PDF":
        return body, None

    ct = (content_type or "").lower()

    if "multipart/form-data" in ct:
        data = _from_multipart(body, content_type)
        if data:
            return data, None
        return None, "no file part found in multipart body"

    if "application/json" in ct or body[:1] in (b"{", b"["):
        try:
            payload = json.loads(body.decode("utf-8", "replace"))
        except Exception:
            return None, "body is not valid JSON"
        if isinstance(payload, list) and payload:
            payload = payload[0]
        for key in ("data", "resume", "file", "pdf", "base64"):
            val = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(val, str) and val:
                if "," in val[:64] and val.lstrip().startswith("data:"):
                    val = val.split(",", 1)[1]
                try:
                    return base64.b64decode(val), None
                except Exception:
                    return None, f"field '{key}' is not valid base64"
        return None, "JSON body has no 'data'/'resume' base64 field"

    # last resort: maybe it's base64 text
    try:
        decoded = base64.b64decode(body, validate=True)
        if decoded[:4] == b"%PDF":
            return decoded, None
    except Exception:
        pass

    return body, None  # let pypdf decide


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(200, {"status": "ok", "usage": "POST a PDF to this endpoint"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            self._send(400, {"error": "missing Content-Length / empty body", "links": []})
            return
        if length > MAX_BYTES:
            self._send(413, {"error": "file too large", "links": []})
            return

        body = self.rfile.read(length)
        pdf_bytes, err = get_pdf_bytes(body, self.headers.get("Content-Type", ""))
        if err:
            self._send(400, {"error": err, "links": []})
            return

        try:
            self._send(200, extract(pdf_bytes))
        except Exception as exc:
            self._send(500, {"error": f"{type(exc).__name__}: {exc}", "links": []})
