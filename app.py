"""Protocol Converter — FastAPI Web 版"""
import os
import io
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.responses import HTMLResponse, FileResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from models.loader import load_protocol
from services.query_engine import QueryEngine
from services.can_codec import CanCodec
from services.excel_parser import ExcelParser

# ── 初始化 ──────────────────────────────────────

VERSION = "v1.2.0"
# 更新源（GitHub 与 Gitee 仓库名不同，各自配置）
SOURCES = [
    {"name": "GitHub", "repo": "littlejazzcat/Protocol_Converter",
     "api": "https://api.github.com/repos/{repo}/releases/latest"},
    {"name": "Gitee", "repo": "littlejazzcat/protocol_converter",
     "api": "https://gitee.com/api/v5/repos/{repo}/releases/latest"},
]

_update_info = {"available": False, "latest": "", "changelog": "",
                "download_url": "", "error": ""}
_download_state = {"active": False, "progress": 0, "downloaded": 0,
                   "total": 0, "path": "", "error": ""}

BASE_DIR = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATE_DIR = BASE_DIR / "templates"

app = FastAPI(title="Protocol Converter")
env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    cache_size=0,
)


def render(name: str, **kwargs):
    return HTMLResponse(env.get_template(name).render(**kwargs))


# 全局状态
state = {
    "protocol": None,
    "query": None,
    "codec": None,
    "parser": None,
    "protocols": {
        "gbt27930_v1.1": "GB/T 27930-2023",
        "anshibo_1k040b": "安世博 UAA-1K040B-E",
        "sg_unified_v107": "三统一 V107",
        "infypower_v107": "英飞源 V107",
    },
    "parse_results": [],
}


def _init_protocol(protocol_id: str):
    json_path = DATA_DIR / f"{protocol_id}.json"
    if not json_path.exists():
        return False
    proto = load_protocol(str(json_path))
    state["protocol"] = proto
    state["query"] = QueryEngine(proto)
    state["codec"] = CanCodec(proto)
    state["parser"] = ExcelParser(state["query"], state["codec"])
    return True


_init_protocol("gbt27930_v1.1")

CUR = lambda: state["protocol"].meta.get("protocol_id", "") if state["protocol"] else ""
ALL_PROTOS = state["protocols"]


# ── 页面路由 ────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return render("index.html", protocols=ALL_PROTOS, current_id=CUR(), version=VERSION)


@app.get("/query", response_class=HTMLResponse)
async def query_page(request: Request):
    return render("index.html", protocols=ALL_PROTOS, current_id=CUR(), version=VERSION)


@app.get("/decode", response_class=HTMLResponse)
async def decode_page(request: Request):
    return render("index.html", protocols=ALL_PROTOS, current_id=CUR(), version=VERSION)


@app.get("/encode", response_class=HTMLResponse)
async def encode_page(request: Request):
    return render("index.html", protocols=ALL_PROTOS, current_id=CUR(), version=VERSION)


@app.get("/parse", response_class=HTMLResponse)
async def parse_page(request: Request):
    return render("index.html", protocols=ALL_PROTOS, current_id=CUR(), version=VERSION)


# ── 协议 API ────────────────────────────────────

@app.post("/api/protocol/select")
async def api_select_protocol(protocol_id: str = Form(...)):
    ok = _init_protocol(protocol_id)
    return {"ok": ok, "name": state["protocols"].get(protocol_id, "")}


@app.get("/api/messages")
async def api_messages(stage: str = "", keyword: str = ""):
    q = state["query"]
    msgs = q.search(keyword) if keyword else (q.by_stage(stage) if stage else q.all_messages())
    return [{"abbr": m.abbr, "name": m.name, "stage": m.stage,
             "pf": m.identifier.get("pf"), "direction": m.direction,
             "data_length": m.data_length, "tp": m.tp} for m in msgs]


@app.get("/api/messages/tree")
async def api_messages_tree():
    proto = state["protocol"]
    result = []
    for group in proto.message_groups:
        stage_msgs = []
        for abbr in group["messages"]:
            msg = proto.get_message_by_abbr(abbr)
            if msg:
                stage_msgs.append({"abbr": msg.abbr, "name": msg.name,
                                   "pf": msg.identifier.get("pf")})
        result.append({"name": group["name"], "messages": stage_msgs})
    return result


# ── 编解码 API ──────────────────────────────────

@app.post("/api/decode")
async def api_decode(can_id: str = Form(...), data: str = Form(...),
                     tp_mode: bool = Form(False)):
    c = state["codec"]
    q = state["query"]
    proto = state["protocol"]

    try:
        id_val = int(can_id.strip().lower().replace("0x", ""), 16)
    except Exception:
        return {"error": "CAN ID 格式错误"}

    try:
        data_bytes = _parse_data_str(data)
    except Exception as e:
        return {"error": f"数据域格式错误: {e}"}

    id_fields = q.parse_can_id(id_val)
    id_detail = []
    for f in proto.can_id_schema.fields:
        v = id_fields.get(f.name)
        hex_v = id_fields.get(f"{f.name}_hex", "")
        if v is not None and f.fixed_value is None:
            desc = f.description or ""
            id_detail.append({"name": f.name, "value": v, "hex": hex_v, "desc": desc})

    direction = _get_direction_display(q, id_val, data_bytes, id_fields)
    msg = q.by_can_id(id_val, data_bytes)

    if msg is None:
        return {"can_id": f"0x{id_val:08X}", "id_detail": id_detail,
                "direction": direction, "message": "UNKNOWN", "fields": []}

    decoded = c.decode(msg, data_bytes)
    fields = []
    for f in msg.fields:
        val = decoded.get(f.name, "")
        if isinstance(val, dict):
            val = val.get("label", str(val))
        unit = f.unit or ""
        fields.append({"name": f.name, "value": str(val) if val is not None else "",
                       "unit": unit})

    return {"can_id": f"0x{id_val:08X}", "id_detail": id_detail,
            "direction": direction, "message": msg.abbr, "message_name": msg.name,
            "fields": fields}


@app.post("/api/encode")
async def api_encode(msg_abbr: str = Form(...)):
    c = state["codec"]
    proto = state["protocol"]
    msg = proto.get_message_by_abbr(msg_abbr)
    if msg is None:
        return {"error": "报文不存在"}

    can_id = c.make_can_id(msg)
    fields = []
    for f in msg.fields:
        fields.append({"name": f.name, "spn": f.spn, "byte_start": f.byte_start,
                       "length": f.length, "data_type": f.data_type,
                       "unit": f.unit or "", "resolution": f.resolution,
                       "offset": f.offset, "default_value": f.default_value,
                       "editable": f.editable, "enum": f.enum})

    return {"can_id": f"0x{can_id:08X}", "can_id_hex": f"{can_id:08X}",
            "data_length": msg.data_length or 0, "fields": fields}


@app.post("/api/encode/build")
async def api_encode_build(msg_abbr: str = Form(...), field_values: str = Form("{}")):
    import json
    c = state["codec"]
    proto = state["protocol"]
    msg = proto.get_message_by_abbr(msg_abbr)
    if msg is None:
        return {"error": "报文不存在"}

    try:
        values = json.loads(field_values)
    except Exception:
        return {"error": "字段值格式错误"}

    try:
        result = c.encode(msg, values)
        can_id = result["can_id"]
        data = result["data"]
    except Exception as e:
        return {"error": str(e)}

    tp_frames = c.tp_split(msg, data, can_id) if msg.tp and msg.data_length and msg.data_length > 6 else []
    return {"can_id": f"0x{can_id:08X}", "can_id_hex": f"{can_id:08X}",
            "data_hex": data.hex(" ").upper(),
            "tp_frames": [{"id": f["can_id_hex"], "data": f["data_hex"], "type": f["type"]}
                          for f in tp_frames]}


# ── 批量解析 API ────────────────────────────────

@app.get("/api/parse/path")
def api_parse_path(path: str = ""):
    parser = state["parser"]
    path = path.strip().strip('"').strip("'")
    try:
        parser.load(path)
    except Exception as e1:
        try:
            import subprocess
            fd, dst = tempfile.mkstemp(
                suffix=".xlsx",
                dir=os.path.dirname(os.path.abspath(path))
            )
            os.close(fd)
            os.unlink(dst)
            r = subprocess.run(["cmd", "/c", "copy", "/y", path, dst],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                raise IOError(f"copy 失败: {r.stderr}")
            parser.load(dst)
            os.unlink(dst)
        except Exception as e2:
            return {"error": f"文件加载失败: {e1} | copy2: {e2}"}

    id_col, data_col = parser.auto_map_columns()
    return {"ok": True, "columns": parser.columns, "row_count": parser.row_count,
            "id_col": id_col, "data_col": data_col,
            "preview": [{**r, "index": i} for i, r in enumerate(parser.preview(20))]}


@app.post("/api/parse/upload")
async def api_parse_upload(file: UploadFile = File(...)):
    parser = state["parser"]
    content = await file.read()

    try:
        parser.load(io.BytesIO(content))
    except Exception:
        try:
            fd, dst = tempfile.mkstemp(suffix=".csv")
            os.close(fd)
            with open(dst, "wb") as f:
                f.write(content)
            parser.load(dst)
            os.unlink(dst)
        except Exception as e:
            return {"error": f"文件加载失败: {e}"}

    id_col, data_col = parser.auto_map_columns()
    return {"ok": True, "columns": parser.columns, "row_count": parser.row_count,
            "id_col": id_col, "data_col": data_col,
            "preview": [{**r, "index": i} for i, r in enumerate(parser.preview(20))]}


@app.post("/api/parse/run")
def api_parse_run():
    parser = state["parser"]
    try:
        results = parser.parse()
    except Exception as e:
        return {"error": str(e)}

    state["parse_results"] = results
    return {"ok": True, "summary": parser.get_summary(), "results": results}


@app.get("/api/parse/export")
def api_parse_export():
    parser = state["parser"]
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    parser.export(path)
    return FileResponse(path, filename="parsed_result.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── 自更新 API ──────────────────────────────────

def _check_update_sync(source_name: str = "") -> dict:
    """同步检测最新版本（GitHub → Gitee 双源容错）"""
    import httpx
    from packaging.version import Version

    names = [source_name] if source_name else [s["name"] for s in SOURCES]
    last_err = ""
    for src in SOURCES:
        if src["name"] not in names:
            continue
        try:
            r = httpx.get(src["api"].format(repo=src["repo"]), timeout=10)
            if r.status_code != 200:
                last_err = f"{src['name']} HTTP {r.status_code}"
                continue
            data = r.json()
            latest_tag = data.get("tag_name", "")
            if not latest_tag:
                last_err = f"{src['name']} 无 tag"
                continue
            asset_url = ""
            for a in data.get("assets", []) or []:
                name = a.get("name", "")
                if name.lower().endswith(".zip"):
                    asset_url = a.get("browser_download_url", "")
                    break
            try:
                available = Version(latest_tag.lstrip("vV")) > Version(VERSION.lstrip("vV"))
            except Exception:
                available = latest_tag != VERSION
            return {
                "available": available,
                "latest": latest_tag,
                "current": VERSION,
                "changelog": (data.get("body") or "")[:500],
                "download_url": asset_url,
                "source": src["name"],
                "error": "",
            }
        except Exception as e:
            last_err = f"{src['name']}: {e}"
            continue
    return {"available": False, "error": f"检测失败: {last_err}"}


@app.get("/api/check-update")
async def api_check_update(source: str = ""):
    result = _check_update_sync(source)
    _update_info.update(result)
    return result


@app.get("/api/download-progress")
async def api_download_progress():
    return _download_state


@app.post("/api/do-update")
def api_do_update():
    if _download_state["active"]:
        return {"ok": False, "error": "已有下载任务进行中"}
    if not _update_info.get("download_url"):
        return {"ok": False, "error": "未找到下载地址，请先检测更新"}
    import httpx

    latest = _update_info.get("latest", "latest")
    dl_dir = Path.home() / "Downloads"
    dl_dir.mkdir(exist_ok=True)
    dst = dl_dir / f"ProtocolConverter_{latest}.zip"

    _download_state.update({"active": True, "progress": 0, "downloaded": 0,
                            "total": 0, "path": str(dst), "error": ""})
    try:
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            with client.stream("GET", _update_info["download_url"]) as resp:
                total = int(resp.headers.get("content-length", 0))
                _download_state["total"] = total
                downloaded = 0
                with open(dst, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        _download_state["downloaded"] = downloaded
                        if total > 0:
                            _download_state["progress"] = int(downloaded / total * 100)
        _download_state["progress"] = 100
        return {"ok": True, "path": str(dst), "latest": latest}
    except Exception as e:
        _download_state["error"] = str(e)
        return {"ok": False, "error": str(e)}
    finally:
        _download_state["active"] = False


# ── 辅助 ─────────────────────────────────────────

def _parse_data_str(s: str) -> bytes:
    s = s.strip().lower()
    for cm in ["//", "#", ";"]:
        idx = s.find(cm)
        if idx >= 0:
            s = s[:idx]
            break
    s = ''.join(c for c in s if c in '0123456789abcdef ')
    s = s.replace(" ", "")
    if not s:
        return b''
    if len(s) % 2 != 0:
        s = '0' + s
    return bytes.fromhex(s)


def _get_direction_display(q, can_id, data, id_fields):
    matcher = q.protocol.message_matcher
    addrs = q.protocol.addresses

    if matcher.type == "data_field" and len(data) > 0:
        mt = data[0] & 0x0F
        return "监控→模块" if mt in (0x00, 0x02) else "模块→监控"

    if matcher.type == "command_number":
        dst = id_fields.get("dest_addr", 0)
        return "模块→监控" if dst in range(0xF0, 0xF9) else "监控→模块"

    sa = id_fields.get("sa", 0)
    ps = id_fields.get("ps", 0)
    sa_name = ""
    ps_name = ""
    for k, v in addrs.items():
        if v.get("value") == sa:
            sa_name = v.get("name", k)
        if v.get("value") == ps:
            ps_name = v.get("name", k)
    if sa_name and ps_name:
        return f"{sa_name}→{ps_name}"
    return ""
