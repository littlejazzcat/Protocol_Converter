"""Excel 批量解析引擎"""

import pandas as pd
from typing import Optional, List, Dict, Any, Tuple

from services.query_engine import QueryEngine
from services.can_codec import CanCodec
from models.protocol import MessageDef


class ExcelParser:
    """Excel CAN 抓包批量解析器"""

    def __init__(self, query: QueryEngine, codec: CanCodec):
        self.query = query
        self.codec = codec
        self._df: Optional[pd.DataFrame] = None
        self._id_col: Optional[str] = None
        self._data_col: Optional[str] = None
        self._results: List[Dict] = []
        self.enable_tp = True  # 是否自动重组 TP 多帧报文

    # ── 加载 ──────────────────────────────────────

    def load(self, filepath: str) -> pd.DataFrame:
        """加载文件，自动识别真实格式（非扩展名）
        也接受 BytesIO / bytes 对象
        """
        import io
        # 如果已经是 bytes/BytesIO，直接尝试 Excel → CSV
        if isinstance(filepath, (bytes, io.BytesIO)):
            data = filepath if isinstance(filepath, bytes) else filepath.getvalue()
            for engine in ["openpyxl", "xlrd"]:
                try:
                    self._df = pd.read_excel(io.BytesIO(data), engine=engine)
                    return self._df
                except Exception:
                    pass
            for enc in ["utf-8", "gbk", "utf-8-sig"]:
                for sep in [",", "\t"]:
                    try:
                        self._df = pd.read_csv(io.BytesIO(data), encoding=enc, sep=sep)
                        if self._df.shape[1] <= 1 and sep == ",":
                            continue
                        return self._df
                    except Exception:
                        pass
            raise ValueError("无法识别文件格式")

        # 文件路径: 先直接试 Excel 引擎
        for engine in ["openpyxl", "xlrd"]:
            try:
                self._df = pd.read_excel(filepath, engine=engine)
                return self._df
            except Exception:
                pass

        # Excel 引擎失败，读文件头判断
        with open(filepath, "rb") as f:
            header = f.read(4)
        is_zip = header[:2] == b"PK"
        last_err = None

        # 如果是 zip 但 Excel 引擎读不了（加密/损坏）
        if is_zip:
            raise ValueError("无法加载 Excel 文件（文件可能已加密或损坏）")

        # CSV / 伪装成 xlsx 的文本文件
        # 先逗号、再制表符
        for enc in ["utf-8", "gbk", "utf-8-sig"]:
            for sep in [",", "\t"]:
                try:
                    self._df = pd.read_csv(filepath, encoding=enc, sep=sep)
                    # 成功但只有一列说明分隔符不对，继续试
                    if self._df.shape[1] <= 1 and sep == ",":
                        continue
                    return self._df
                except Exception as e:
                    last_err = e

        # 全失败: 最后当二进制 Excel 再试一次
        try:
            self._df = pd.read_excel(filepath, engine="openpyxl")
            return self._df
        except Exception:
            pass

        raise ValueError(f"无法加载文件: {last_err}")

    # ── 列映射 ────────────────────────────────────

    def auto_map_columns(self) -> Tuple[Optional[str], Optional[str]]:
        """自动识别 CAN ID 列和数据域列"""
        if self._df is None:
            return None, None

        id_keywords = ["帧id", "canid", "can", "id", "标识符"]
        # 数据列: 先精确匹配含 hex 的列，再模糊匹配
        hex_keywords = ["hex", "数据(hex", "data(hex"]
        data_keywords = ["数据", "data", "报文", "dat"]

        id_col, data_col = None, None

        for col in self._df.columns:
            col_lower = str(col).lower().replace(" ", "").replace("_", "")
            if id_col is None:
                for kw in id_keywords:
                    if kw in col_lower:
                        id_col = col
                        break

        # 数据列: 优先含 hex 的
        for col in self._df.columns:
            col_lower = str(col).lower().replace(" ", "").replace("_", "")
            for kw in hex_keywords:
                if kw in col_lower:
                    data_col = col
                    break
            if data_col:
                break

        # 找不到 hex 列，降级模糊匹配
        if data_col is None:
            for col in self._df.columns:
                col_lower = str(col).lower().replace(" ", "").replace("_", "")
                for kw in data_keywords:
                    if kw in col_lower:
                        data_col = col
                        break
                if data_col:
                    break

        self._id_col = id_col
        self._data_col = data_col
        return id_col, data_col

    def set_columns(self, id_col: str, data_col: str):
        """手动指定列名"""
        self._id_col = id_col
        self._data_col = data_col

    @property
    def columns(self) -> List[str]:
        return list(self._df.columns) if self._df is not None else []

    @property
    def row_count(self) -> int:
        return len(self._df) if self._df is not None else 0

    def preview(self, n: int = 20) -> pd.DataFrame:
        """返回前 n 行预览"""
        return self._df.head(n) if self._df is not None else pd.DataFrame()

    # ── 解析 ──────────────────────────────────────

    def parse(self, progress_callback=None) -> List[Dict]:
        """批量解析所有行，自动处理 TP 多帧重组"""
        if self._df is None or self._id_col is None or self._data_col is None:
            raise ValueError("请先加载 Excel 并完成列映射")

        self._results = []
        total = len(self._df)
        match_count = 0
        fail_count = 0
        unknown_count = 0

        # TP 收集器: {(src, dst): {"rts": {...}, "dt_frames": [(seq, bytes), ...], "start_idx": int}}
        tp_groups: Dict[tuple, dict] = {}
        tp_indices: set = set()  # 被 TP 组覆盖的行索引

        keep_cols = [c for c in self._df.columns
                     if c not in (self._id_col, self._data_col)
                     and not str(c).startswith("Unnamed")]

        # ── 第一遍: 逐行解析，TP 帧暂存 ──
        for i, (_, row) in enumerate(self._df.iterrows()):
            result = {"_index": i}
            for col in keep_cols:
                result[col] = row[col]

            try:
                can_id = self._parse_can_id(row[self._id_col])
                result["CAN ID"] = f"0x{can_id:08X}"
                data = self._parse_data(row[self._data_col])
                # CAN ID 位域解析（含描述、方向）
                id_fields = self.query.parse_can_id(can_id)
                id_parts = []
                for sf in self.query.protocol.can_id_schema.fields:
                    v = id_fields.get(sf.name)
                    if v is not None and sf.fixed_value is None:
                        desc = sf.description or ""
                        id_parts.append(f"{sf.name}={v}(0x{v:X})" + (f"[{desc}]" if desc else ""))
                direction = self._get_direction(can_id, data, id_fields)
                result["CAN ID 解析"] = (direction + " | " if direction else "") + "; ".join(id_parts)
                result["数据域"] = data.hex(" ").upper() if data else ""
                result["数据域"] = data.hex(" ").upper() if data else ""

                pf = (can_id >> 16) & 0xFF

                # TP 帧检测
                if self.enable_tp and pf in (0xEB, 0xEC) and len(data) >= 5:
                    sa = can_id & 0xFF
                    ps = (can_id >> 8) & 0xFF
                    key = (sa, ps)

                    if pf == 0xEC:
                        # TP.CM (RTS/CTS)
                        if key not in tp_groups:
                            tp_groups[key] = {"rts": None, "dt_frames": [], "start_idx": i,
                                               "keep_cols": {c: row[c] for c in keep_cols}}
                        tp_groups[key]["rts"] = {"can_id": can_id, "data": data}
                        tp_indices.add(i)
                    elif pf == 0xEB:
                        # TP.DT
                        if key not in tp_groups:
                            tp_groups[key] = {"rts": None, "dt_frames": [], "start_idx": i,
                                               "keep_cols": {c: row[c] for c in keep_cols}}
                        seq = data[0]
                        tp_groups[key]["dt_frames"].append((seq, data))
                        tp_indices.add(i)
                    continue  # TP 帧不单独生成结果行

                # 普通帧解码
                msg = self.query.by_can_id(can_id, data)
                if msg is None:
                    result["报文"] = "UNKNOWN"
                    result["解析结果"] = ""
                    unknown_count += 1
                else:
                    result["报文"] = msg.abbr
                    result["解析结果"] = self._format_decoded(msg, data)
                    match_count += 1
            except Exception as e:
                result["报文"] = "ERROR"
                result["解析结果"] = str(e)[:80]
                fail_count += 1

            self._results.append(result)

            if progress_callback:
                progress_callback(i + 1, total)

        # ── 第二遍: 重组 TP 帧 ──
        tp_count = 0
        for key, group in tp_groups.items():
            if not group["dt_frames"]:
                continue
            # 按序列号排序
            group["dt_frames"].sort(key=lambda x: x[0])
            frames_data = [f[1] for f in group["dt_frames"]]
            try:
                assembled = self.codec.tp_reassemble(frames_data)
            except Exception:
                continue

            # 确定目标报文: 从 RTS 中提取 PGN
            target_msg = None
            if group["rts"]:
                rts_data = group["rts"]["data"]
                target_pgn = rts_data[5] | (rts_data[6] << 8) | (rts_data[7] << 16)
                target_pf = target_pgn >> 8
                target_msg = self.query.by_pf(target_pf)

            # 如果找不到目标报文，按数据长度猜
            if target_msg is None:
                for m in self.query.all_messages():
                    if m.tp and m.data_length and m.data_length == len(assembled):
                        target_msg = m
                        break

            if target_msg:
                result = {"_index": group["start_idx"], "_tp": True}
                result.update(group["keep_cols"])
                result["CAN ID"] = f"0x{group['rts']['can_id']:08X}" if group["rts"] else "TP"
                if group["rts"]:
                    id_fields = self.query.parse_can_id(group["rts"]["can_id"])
                    id_parts = []
                    for sf in self.query.protocol.can_id_schema.fields:
                        v = id_fields.get(sf.name)
                        if v is not None:
                            id_parts.append(f"{sf.name}={v}")
                    result["CAN ID 解析"] = "; ".join(id_parts)
                result["数据域"] = assembled.hex(" ").upper()
                result["报文"] = f"{target_msg.abbr} [TP]"
                result["解析结果"] = self._format_decoded(target_msg, assembled)
                # 插入到起始位置
                self._results.append(result)
                tp_count += 1

        # 按 _index 排序（TP 行插入到对应位置）
        self._results.sort(key=lambda r: r["_index"])

        return self._results

    def _format_decoded(self, msg, data: bytes) -> str:
        """格式化解码结果为字符串"""
        decoded = self.codec.decode(msg, data)
        parts = []
        for field in msg.fields:
            val = decoded.get(field.name, "")
            if isinstance(val, dict):
                val = val.get("label", str(val))
            if val == "" or val is None:
                continue
            unit = f"{field.unit}" if field.unit else ""
            parts.append(f"{field.name}={val}{unit}")
        return "; ".join(parts) if parts else ""

    def get_summary(self) -> Dict[str, int]:
        """返回解析汇总"""
        matched = sum(1 for r in self._results if r.get("报文") not in ("UNKNOWN", "ERROR", None))
        unknown = sum(1 for r in self._results if r.get("报文") == "UNKNOWN")
        error = sum(1 for r in self._results if r.get("报文") == "ERROR")
        tp = sum(1 for r in self._results if r.get("_tp"))
        return {
            "total": len(self._results),
            "matched": matched,
            "unknown": unknown,
            "error": error,
            "tp": tp,
        }

    def to_dataframe(self) -> pd.DataFrame:
        """将结果转为 DataFrame"""
        return pd.DataFrame(self._results)

    # ── 导出 ──────────────────────────────────────

    def export(self, filepath: str):
        """导出解析结果为 Excel"""
        df = self.to_dataframe()
        cols = [c for c in df.columns if c not in ("_index", "_tp")]
        df[cols].to_excel(filepath, index=False)

    # ── 内部 ──────────────────────────────────────

    def _get_direction(self, can_id: int, data: bytes, id_fields: dict) -> str:
        """根据协议判断报文方向"""
        matcher = self.query.protocol.message_matcher
        addrs = self.query.protocol.addresses

        # 安世博: MessageType nibble
        if matcher.type == "data_field" and len(data) > 0:
            mt = data[0] & 0x0F
            if mt in (0x00, 0x02):
                return f"监控→模块"
            else:
                return f"模块→监控"

        # 英飞源: dest/src 地址
        if matcher.type == "command_number":
            dst = id_fields.get("dest_addr", 0)
            src = id_fields.get("source_addr", 0)
            if dst in range(0xF0, 0xF9):
                return f"模块→监控"
            else:
                return f"监控→模块"

        # 27930 / 三统一: PF-based, 根据 SA 判断
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

    def _parse_can_id(self, value) -> int:
        """解析 CAN ID 值（支持 hex 字符串 / 十进制整数）"""
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value).strip().lower().replace("0x", "").replace(" ", "")
        return int(s, 16)

    def _parse_data(self, value) -> bytes:
        """解析数据域（hex 字符串），容错处理"""
        if isinstance(value, bytes):
            return value
        s = str(value).strip().lower()
        # 切掉注释 (// 或 # 之后的内容)
        for comment_marker in ["//", "#", ";"]:
            idx = s.find(comment_marker)
            if idx >= 0:
                s = s[:idx]
                break
        # 移除常见前缀
        for prefix in ["0x", "(", "[", "'", '"']:
            if s.startswith(prefix):
                s = s[len(prefix):]
        # 移除常见后缀
        for suffix in [")", "]", "'", '"']:
            if s.endswith(suffix):
                s = s[:-len(suffix)]
        # 只保留 hex 字符和空格
        s = ''.join(c for c in s if c in '0123456789abcdef ')
        s = s.replace(" ", "")
        if not s:
            return b''
        # 补齐奇数长度
        if len(s) % 2 != 0:
            s = '0' + s
        return bytes.fromhex(s)
