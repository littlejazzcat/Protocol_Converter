"""JSON 协议定义文件加载器"""

import json
from pathlib import Path
from typing import Optional

from .protocol import (
    ProtocolDefinition, MessageDef, FieldDef,
    CanIdSchema, CanIdField, MessageMatcher
)


def load_protocol(filepath: str) -> ProtocolDefinition:
    """从 JSON 文件加载协议定义"""
    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return _parse_protocol(raw)


def _parse_protocol(raw: dict) -> ProtocolDefinition:
    """解析原始 JSON 字典为 ProtocolDefinition"""
    # CAN ID schema
    schema_raw = raw.get("can_id_schema", {})
    can_id_schema = CanIdSchema(
        total_bits=schema_raw.get("total_bits", 29),
        fields=[
            CanIdField(
                name=f["name"],
                bit_start=f["bit_start"],
                bit_len=f["bit_len"],
                description=f.get("description", ""),
                fixed_value=f.get("fixed_value"),
                enum={int(k): v for k, v in f.get("enum", {}).items()} if f.get("enum") else None,
            )
            for f in schema_raw.get("fields", [])
        ],
        message_identifier=schema_raw.get("message_identifier", "pf"),
        identifier_field=schema_raw.get("identifier_field", "pf"),
    )

    # Message matcher
    matcher_raw = raw.get("message_matcher", {})
    message_matcher = MessageMatcher(
        type=matcher_raw.get("type", "pf_based"),
        match_field=matcher_raw.get("match_field", "pf"),
        match_byte=matcher_raw.get("match_byte"),
        aux_field=matcher_raw.get("aux_field"),
        aux_byte=matcher_raw.get("aux_byte"),
        aux_nibble=matcher_raw.get("aux_nibble"),
    )

    # Messages
    messages = []
    for m_raw in raw.get("messages", []):
        fields = []
        for f_raw in m_raw.get("fields", []):
            # 处理嵌套 bit_fields
            if f_raw.get("bit_fields"):
                for bf in f_raw["bit_fields"]:
                    fields.append(FieldDef(
                        name=bf["name"],
                        byte_start=f_raw.get("byte_start", 1),
                        length=f_raw.get("length", 1),
                        bit_start=bf.get("bit_start"),
                        bit_len=bf.get("bit_len"),
                        data_type="bits",
                        enum={int(k): v for k, v in bf.get("enum", {}).items()} if bf.get("enum") else None,
                        required=f_raw.get("required", True),
                        editable=f_raw.get("editable", True),
                    ))
            else:
                fields.append(FieldDef(
                    name=f_raw.get("name", ""),
                    spn=f_raw.get("spn"),
                    byte_start=f_raw.get("byte_start", 1),
                    length=f_raw.get("length", 1),
                    bit_start=f_raw.get("bit_start"),
                    bit_len=f_raw.get("bit_len"),
                    data_type=f_raw.get("data_type", "int_le"),
                    resolution=f_raw.get("resolution"),
                    offset=f_raw.get("offset"),
                    unit=f_raw.get("unit"),
                    range_min=f_raw.get("range_min"),
                    range_max=f_raw.get("range_max"),
                    enum={int(k): v for k, v in f_raw.get("enum", {}).items()} if f_raw.get("enum") else None,
                    required=f_raw.get("required", True),
                    editable=f_raw.get("editable", True),
                    default_value=f_raw.get("default_value"),
                ))

        messages.append(MessageDef(
            name=m_raw.get("name", ""),
            abbr=m_raw.get("abbr", ""),
            identifier=m_raw.get("identifier", {}),
            can_id_template=m_raw.get("can_id_template", {}),
            direction=m_raw.get("direction", ""),
            cycle_ms=m_raw.get("cycle_ms", 0),
            data_length=m_raw.get("data_length"),
            tp=m_raw.get("tp", False),
            stage=m_raw.get("stage", ""),
            fields=fields,
            description=m_raw.get("description", ""),
        ))

    return ProtocolDefinition(
        meta=raw.get("meta", {}),
        can_id_schema=can_id_schema,
        addresses=raw.get("addresses", {}),
        encoding_rules=raw.get("encoding_rules", {}),
        message_matcher=message_matcher,
        message_groups=raw.get("message_groups", []),
        messages=messages,
    )


def validate_integrity(protocol: ProtocolDefinition) -> list[str]:
    """校验协议定义的完整性，返回错误信息列表。

    检查项：
    1. 字段字节越界
    2. 同字节内位域重叠
    3. 报文标识符唯一性（按 message_matcher.type）
    4. data_type 一致性
    5. message_groups 引用完整性
    6. CAN ID Schema 位域不重叠
    7. 报文基础字段完整性（name/abbr 不空）
    """
    errors: list[str] = []
    matcher = protocol.message_matcher
    all_abbrs = {m.abbr for m in protocol.messages}

    # ── 0. 报文基础字段 ──
    for msg in protocol.messages:
        if not msg.name.strip():
            errors.append(f"报文 abbr='{msg.abbr}' 缺少 name")
        if not msg.abbr.strip():
            errors.append(f"报文 name='{msg.name}' 缺少 abbr")

    # ── 1. 字段字节越界 ──
    for msg in protocol.messages:
        dl = msg.data_length
        if dl is None:
            continue
        for field in msg.fields:
            if field.bit_start is not None:
                if field.byte_start > dl:
                    errors.append(
                        f"[{msg.abbr}] field '{field.name}': "
                        f"byte_start={field.byte_start} > data_length={dl}"
                    )
            else:
                end = field.byte_start + field.length - 1
                if end > dl:
                    errors.append(
                        f"[{msg.abbr}] field '{field.name}': "
                        f"bytes {field.byte_start}-{end} 越界 (data_length={dl})"
                    )

    # ── 2. 同字节位域重叠 ──
    for msg in protocol.messages:
        byte_bit_map: dict[int, list[FieldDef]] = {}
        for field in msg.fields:
            if field.bit_start is not None and field.bit_len is not None:
                byte_bit_map.setdefault(field.byte_start, []).append(field)
        for byte_idx, fields in byte_bit_map.items():
            ranges = sorted(
                [(f.bit_start, f.bit_start + f.bit_len - 1, f.name) for f in fields]
            )
            for i in range(len(ranges) - 1):
                if ranges[i][1] >= ranges[i + 1][0]:
                    errors.append(
                        f"[{msg.abbr}] Byte{byte_idx} 位域重叠: "
                        f"'{ranges[i][2]}' [{ranges[i][0]}:{ranges[i][1]}] vs "
                        f"'{ranges[i + 1][2]}' [{ranges[i + 1][0]}:{ranges[i + 1][1]}]"
                    )

    # ── 3. 标识符唯一性 ──
    if matcher.type == "pf_based":
        seen: dict[int, str] = {}
        for msg in protocol.messages:
            pf = msg.identifier.get("pf")
            if pf is not None:
                if pf in seen:
                    errors.append(
                        f"PF 0x{pf:02X} 重复: '{seen[pf]}' 和 '{msg.abbr}'"
                    )
                seen[pf] = msg.abbr

    elif matcher.type == "data_field":
        seen: dict[tuple, str] = {}
        for msg in protocol.messages:
            ct = msg.identifier.get("command_type")
            mt = None
            for f in msg.fields:
                if not f.editable and f.data_type == "bits" and f.bit_start == 0:
                    mt = f.default_value
                    break
            key = (ct, mt)
            if ct is not None:
                if key in seen:
                    errors.append(
                        f"(CommandType={ct}, MsgType={mt}) 重复: "
                        f"'{seen[key]}' 和 '{msg.abbr}'"
                    )
                seen[key] = msg.abbr

    elif matcher.type == "command_number":
        seen: dict[int, str] = {}
        for msg in protocol.messages:
            cmd = msg.identifier.get("command_number")
            if cmd is not None:
                if cmd in seen:
                    errors.append(
                        f"CommandNumber 0x{cmd:02X} 重复: '{seen[cmd]}' 和 '{msg.abbr}'"
                    )
                seen[cmd] = msg.abbr

    # ── 4. data_type 一致性 ──
    for msg in protocol.messages:
        for field in msg.fields:
            if field.data_type == "bits":
                if field.bit_start is None or field.bit_len is None:
                    errors.append(
                        f"[{msg.abbr}] field '{field.name}': "
                        f"bits 类型缺少 bit_start/bit_len"
                    )
            elif field.data_type == "float_ieee754":
                if field.length != 4:
                    errors.append(
                        f"[{msg.abbr}] field '{field.name}': "
                        f"float_ieee754 要求 length=4，实际 {field.length}"
                    )

    # ── 5. message_groups 引用完整性 ──
    for group in protocol.message_groups:
        group_name = group.get("name", "?")
        for abbr in group.get("messages", []):
            if abbr not in all_abbrs:
                errors.append(
                    f"message_group '{group_name}' 引用了不存在的缩写 '{abbr}'"
                )

    # ── 6. CAN ID Schema 位域不重叠 ──
    schema_ranges = sorted(
        [(f.bit_start, f.bit_start + f.bit_len - 1, f.name)
         for f in protocol.can_id_schema.fields]
    )
    for i in range(len(schema_ranges) - 1):
        if schema_ranges[i][1] >= schema_ranges[i + 1][0]:
            errors.append(
                f"CAN ID Schema 位域重叠: "
                f"'{schema_ranges[i][2]}' [{schema_ranges[i][0]}:{schema_ranges[i][1]}] vs "
                f"'{schema_ranges[i + 1][2]}' [{schema_ranges[i + 1][0]}:{schema_ranges[i + 1][1]}]"
            )

    return errors
