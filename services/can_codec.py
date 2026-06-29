"""编解码器 — 协议无关的 CAN 帧解码"""

import struct
from typing import Optional, Dict, Any, List

from models.protocol import ProtocolDefinition, MessageDef, FieldDef


class CanCodec:
    """CAN 帧编解码器，构造时注入协议定义"""

    def __init__(self, protocol: ProtocolDefinition):
        self.protocol = protocol
        self._rules = protocol.encoding_rules

    # ── 解码 ──────────────────────────────────────

    def decode(self, msg: MessageDef, data: bytes) -> Dict[str, Any]:
        """解码数据域 → 物理量字典"""
        result = {}
        for field in msg.fields:
            try:
                value = self._unpack_field(field, data)
                result[field.name] = value
            except Exception as e:
                result[field.name] = f"[解码失败: {e}]"
        return result

    def _unpack_field(self, field: FieldDef, data: bytes) -> Any:
        """根据 data_type 分派解包"""
        if field.data_type == "bits":
            return self._unpack_bits(field, data)
        elif field.data_type == "bcd":
            return self._unpack_bcd(field, data)
        elif field.data_type == "ascii":
            return self._unpack_ascii(field, data)
        elif field.data_type == "float_ieee754":
            return self._unpack_float(field, data)
        elif field.data_type == "int_be":
            return self._unpack_int_be(field, data)
        else:  # int_le (default)
            return self._unpack_int_le(field, data)

    def _unpack_int_le(self, field: FieldDef, data: bytes) -> Any:
        raw = self._read_bytes_le(data, field.byte_start - 1, field.length)
        if field.enum:
            return {"value": raw, "label": field.enum.get(raw, str(raw))}
        if field.resolution is not None:
            phys = raw * field.resolution
            if field.offset is not None:
                phys += field.offset
            return round(phys, 4)
        return raw

    def _unpack_int_be(self, field: FieldDef, data: bytes) -> Any:
        raw = self._read_bytes_be(data, field.byte_start - 1, field.length)
        if field.enum:
            return {"value": raw, "label": field.enum.get(raw, str(raw))}
        if field.resolution is not None:
            phys = raw * field.resolution
            if field.offset is not None:
                phys += field.offset
            return round(phys, 4)
        return raw

    def _unpack_float(self, field: FieldDef, data: bytes) -> Any:
        start = field.byte_start - 1
        chunk = data[start:start + 4]
        if len(chunk) < 4:
            raise ValueError(f"数据不足: 需要4字节浮点, 实际{len(chunk)}字节")
        return round(struct.unpack(">f", chunk)[0], 4)

    def _unpack_bits(self, field: FieldDef, data: bytes) -> Any:
        byte_idx = field.byte_start - 1
        if byte_idx >= len(data):
            raise ValueError(f"字节越界: byte{field.byte_start}, 数据长度{len(data)}")
        byte_val = data[byte_idx]
        mask = ((1 << field.bit_len) - 1) << field.bit_start
        raw = (byte_val & mask) >> field.bit_start
        if field.enum:
            return {"value": raw, "label": field.enum.get(raw, str(raw))}
        return raw

    def _unpack_bcd(self, field: FieldDef, data: bytes) -> Any:
        start = field.byte_start - 1
        chunk = data[start:start + field.length]
        parts = []
        for b in chunk:
            parts.append(f"{b:02X}")
        return " ".join(parts)

    def _unpack_ascii(self, field: FieldDef, data: bytes) -> Any:
        start = field.byte_start - 1
        chunk = data[start:start + field.length]
        return chunk.decode("ascii", errors="replace").strip("\x00").strip()

    # ── 工具方法 ──────────────────────────────────

    @staticmethod
    def _read_bytes_le(data: bytes, offset: int, length: int) -> int:
        """从字节数组读取 Little-Endian 整数"""
        if offset + length > len(data):
            raise ValueError(f"数据不足: offset={offset}, length={length}, 数据长度={len(data)}")
        chunk = data[offset:offset + length]
        return int.from_bytes(chunk, "little")

    @staticmethod
    def _read_bytes_be(data: bytes, offset: int, length: int) -> int:
        """从字节数组读取 Big-Endian 整数"""
        if offset + length > len(data):
            raise ValueError(f"数据不足: offset={offset}, length={length}, 数据长度={len(data)}")
        chunk = data[offset:offset + length]
        return int.from_bytes(chunk, "big")

    # ── 编码 ──────────────────────────────────────

    def encode(self, msg: MessageDef, params: Dict[str, Any]) -> Dict[str, Any]:
        """编码物理量 → CAN 帧
        params: {"字段名": 物理量值, ...}  或  {"字段名": {"label": "枚举名"}, ...}
        返回: {"can_id": int, "can_id_hex": str, "data": bytes, "data_hex": str}
        """
        data_length = msg.data_length or 8
        data = bytearray(data_length)

        # 自动填充不可编辑字段的默认值
        for field in msg.fields:
            if not field.editable:
                if field.name not in params:
                    if field.default_value is not None:
                        params[field.name] = field.default_value
                    elif field.data_type == "bits" and field.enum:
                        params[field.name] = list(field.enum.keys())[0]
                    else:
                        params[field.name] = 0

        # 先处理整字节字段，再处理 bit 字段（避免覆盖）
        byte_fields = [f for f in msg.fields if f.data_type != "bits"]
        bit_fields = [f for f in msg.fields if f.data_type == "bits"]

        for field in byte_fields:
            if field.name in params:
                packed = self._pack_field(field, params[field.name])
                start = field.byte_start - 1
                data[start:start + len(packed)] = packed

        # bit 字段：按字节分组，合并写入
        if bit_fields:
            byte_bit_map: Dict[int, List[FieldDef]] = {}
            for f in bit_fields:
                byte_idx = f.byte_start - 1
                byte_bit_map.setdefault(byte_idx, []).append(f)

            for byte_idx, fields in byte_bit_map.items():
                byte_val = data[byte_idx] if byte_idx < len(data) else 0
                for f in fields:
                    if f.name in params:
                        raw_val = self._resolve_enum_value(f, params[f.name])
                        mask = ((1 << f.bit_len) - 1) << f.bit_start
                        byte_val = (byte_val & ~mask) | ((raw_val << f.bit_start) & mask)
                if byte_idx < len(data):
                    data[byte_idx] = byte_val

        can_id = self.make_can_id(msg)

        # TP 分包
        if msg.tp and len(data) > 8:
            tp_frames = self.tp_split(msg, bytes(data), can_id)
            return {
                "can_id": can_id,
                "can_id_hex": f"0x{can_id:08X}",
                "data": bytes(data),
                "data_hex": bytes(data).hex(" ").upper(),
                "tp": True,
                "tp_frames": tp_frames,
                "tp_info": f"共 {len(data)} 字节, 分 {len(tp_frames)} 帧 (TP)",
            }

        return {
            "can_id": can_id,
            "can_id_hex": f"0x{can_id:08X}",
            "data": bytes(data),
            "data_hex": bytes(data).hex(" ").upper(),
        }

    def tp_split(self, msg: MessageDef, data: bytes, base_can_id: int) -> list:
        """将长报文按 27930/J1939 TP 分包
        返回: [{"frame": N, "can_id": int, "can_id_hex": str, "data": bytes, "data_hex": str, "type": str}, ...]
        """
        frames = []
        total_len = len(data)
        total_packets = (total_len + 6) // 7
        pgn = msg.pgn or 0

        # TP.CM_RTS — PGN 0xEC00
        rts_id = (base_can_id & 0xFF00FFFF) | (0xEC << 16)
        rts = bytearray(8)
        rts[0] = 0x10
        rts[1] = total_len & 0xFF
        rts[2] = (total_len >> 8) & 0xFF
        rts[3] = total_packets & 0xFF
        rts[4] = 0xFF
        rts[5] = pgn & 0xFF; rts[6] = (pgn >> 8) & 0xFF; rts[7] = (pgn >> 16) & 0xFF
        frames.append({"frame": 0, "can_id": rts_id, "can_id_hex": f"0x{rts_id:08X}", "data": bytes(rts), "data_hex": rts.hex(" ").upper(), "type": "TP.CM_RTS"})

        # TP.CM_CTS
        cts = bytearray(8)
        cts[0] = 0x11; cts[1] = total_packets & 0xFF; cts[2] = 1; cts[3] = 0xFF; cts[4] = 0xFF
        cts[5] = pgn & 0xFF; cts[6] = (pgn >> 8) & 0xFF; cts[7] = (pgn >> 16) & 0xFF
        frames.append({"frame": 0, "can_id": rts_id, "can_id_hex": f"0x{rts_id:08X}", "data": bytes(cts), "data_hex": cts.hex(" ").upper(), "type": "TP.CM_CTS"})

        # TP.DT — PGN 0xEB00
        dt_id = (base_can_id & 0xFF00FFFF) | (0xEB << 16)
        seq, offset = 1, 0
        first = bytearray(8)
        first[0] = 0x10 | ((total_len >> 8) & 0x0F)
        first[1] = total_len & 0xFF
        n = min(6, total_len); first[2:2 + n] = data[0:n]
        frames.append({"frame": seq, "can_id": dt_id, "can_id_hex": f"0x{dt_id:08X}", "data": bytes(first), "data_hex": first.hex(" ").upper(), "type": "TP.DT 首帧"})
        seq += 1; offset += n
        while offset < total_len:
            dt = bytearray(8); dt[0] = seq
            n = min(7, total_len - offset); dt[1:1 + n] = data[offset:offset + n]
            frames.append({"frame": seq, "can_id": dt_id, "can_id_hex": f"0x{dt_id:08X}", "data": bytes(dt), "data_hex": dt.hex(" ").upper(), "type": "TP.DT"})
            seq += 1; offset += n
        return frames

    def tp_reassemble(self, frames: list) -> bytes:
        """从 TP.DT 帧序列重组完整数据
        frames: [bytes, ...] — 每帧 8 字节 TP.DT 数据（含序号头）
        返回: 重组后的完整数据
        """
        if not frames:
            return b''
        result = bytearray()
        total_len = 0
        for i, f in enumerate(frames):
            if len(f) < 2:
                continue
            if i == 0:
                # 首帧: byte0 高 nibble=0x1, byte1=总长度低 8 位, byte2-7=前 6 字节
                total_len = ((f[0] & 0x0F) << 8) | f[1]
                result.extend(f[2:min(2 + 6, len(f))])
            else:
                # 后续帧: byte0=序号, byte1-7=7 字节数据
                result.extend(f[1:min(8, len(f))])
        if total_len:
            return bytes(result[:total_len])
        return bytes(result)

    def make_can_id(self, msg: MessageDef) -> int:
        """根据 MessageDef 的 can_id_template 构造 CAN ID"""
        t = msg.can_id_template
        # 27930: CAN ID = P(3) << 26 | PF(8) << 16 | PS(8) << 8 | SA(8)
        can_id = 0
        for field_def in self.protocol.can_id_schema.fields:
            name = field_def.name
            if name in t:
                val = t[name]
            elif field_def.fixed_value is not None:
                val = field_def.fixed_value
            else:
                val = 0
            can_id |= (val & ((1 << field_def.bit_len) - 1)) << field_def.bit_start
        return can_id

    def _pack_field(self, field: FieldDef, value: Any) -> bytes:
        """根据 data_type 分派打包"""
        if field.data_type == "int_be":
            return self._pack_int_be(field, value)
        elif field.data_type == "bcd":
            return self._pack_bcd(field, value)
        elif field.data_type == "ascii":
            return self._pack_ascii(field, value)
        elif field.data_type == "float_ieee754":
            return self._pack_float(field, value)
        else:  # int_le (default)
            return self._pack_int_le(field, value)

    def _pack_int_le(self, field: FieldDef, value: Any) -> bytes:
        raw = self._resolve_enum_value(field, value)
        if field.resolution is not None:
            raw = int(round((raw - (field.offset or 0)) / field.resolution + 1e-9))
        elif isinstance(raw, float):
            raw = int(round(raw))  # 无分辨率的浮点输入 → 整数
        return raw.to_bytes(field.length, "little")

    def _pack_int_be(self, field: FieldDef, value: Any) -> bytes:
        raw = self._resolve_enum_value(field, value)
        if field.resolution is not None:
            raw = int(round((raw - (field.offset or 0)) / field.resolution + 1e-9))
        elif isinstance(raw, float):
            raw = int(round(raw))  # 无分辨率的浮点输入 → 整数
        return raw.to_bytes(field.length, "big")

    def _pack_bcd(self, field: FieldDef, value: Any) -> bytes:
        """压缩 BCD 编码: 字符串 "13 20 15 11 10 20 19" → bytes"""
        if isinstance(value, str):
            parts = value.strip().split()
            return bytes(int(p, 16) for p in parts)
        return bytes(value)

    def _pack_ascii(self, field: FieldDef, value: Any) -> bytes:
        text = str(value) if not isinstance(value, str) else value
        result = text.encode("ascii", errors="replace")
        if len(result) < field.length:
            result += b'\x00' * (field.length - len(result))
        return result[:field.length]

    def _pack_float(self, field: FieldDef, value: Any) -> bytes:
        return struct.pack(">f", float(value))

    def _resolve_enum_value(self, field: FieldDef, value: Any):
        """枚举值解析: 支持 dict/str/直接数值。

        注意: float 输入不截断为 int, 保留原值供分辨率转换处理。
        例如 365.1 (物理值) 配合 resolution=0.1 → raw=3651, 而非 int(365.1)=365。
        """
        if isinstance(value, dict):
            return int(value.get("value", 0))
        if isinstance(value, str) and field.enum:
            for k, v in field.enum.items():
                if v == value or str(k) == value:
                    return int(k)
            # 尝试直接解析为数字
            try:
                return int(value)
            except ValueError:
                raise ValueError(f"无法将 '{value}' 映射为枚举值, 可选: {list(field.enum.values())}")
        if isinstance(value, float):
            return value  # 保留浮点, 分辨率转换时处理
        if isinstance(value, int):
            return value
        raise ValueError(f"无法解析字段值: {value}")

    # ── 格式化 ────────────────────────────────────

    def format_decode_result(self, msg: MessageDef, result: Dict[str, Any]) -> List[Dict[str, str]]:
        """将解码结果格式化为表格行"""
        rows = []
        for field in msg.fields:
            value = result.get(field.name, "N/A")
            display_value = value
            unit_str = field.unit or ""

            if isinstance(value, dict) and "label" in value:
                display_value = f"{value['label']} ({value['value']})"
            elif isinstance(value, float):
                display_value = f"{value} {unit_str}".strip()
            elif isinstance(value, int) and field.unit:
                display_value = f"{value} {unit_str}".strip()

            rows.append({
                "字段": field.name,
                "SPN": str(field.spn) if field.spn else "-",
                "字节": f"Byte{field.byte_start}" + (f".{field.bit_start}" if field.bit_start is not None else ""),
                "长度": f"{field.bit_len}bit" if field.bit_len else f"{field.length}B",
                "解码值": str(display_value),
            })
        return rows
