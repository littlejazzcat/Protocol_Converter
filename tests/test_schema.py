"""JSON 结构校验 — 验证四份协议定义文件的结构合法性

比完整性校验 (test_integrity.py) 更底层：检查字段存在性、类型正确性，
在 ProtocolDefinition 反序列化之前就能发现的格式问题。
"""

import json
import os
import pytest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

PROTO_FILES = [
    "gbt27930_v1.1.json",
    "anshibo_1k040b.json",
    "sg_unified_v107.json",
    "infypower_v107.json",
]


def _load_json(filename: str) -> dict:
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════
#  顶层结构校验
# ═══════════════════════════════════════════════

REQUIRED_TOP_KEYS = [
    "meta", "can_id_schema", "addresses", "encoding_rules",
    "message_matcher", "message_groups", "messages",
]


@pytest.mark.parametrize("filename", PROTO_FILES)
def test_top_level_keys(filename):
    """所有协议 JSON 应包含全部必需顶层键"""
    data = _load_json(filename)
    for key in REQUIRED_TOP_KEYS:
        assert key in data, f"[{filename}] 缺少顶层键 '{key}'"


# ═══════════════════════════════════════════════
#  meta 段校验
# ═══════════════════════════════════════════════

META_REQUIRED = ["protocol_name", "protocol_id", "version", "baud_rate", "frame_format"]


@pytest.mark.parametrize("filename", PROTO_FILES)
def test_meta_fields(filename):
    """meta 段应包含全部必需字段"""
    data = _load_json(filename)
    meta = data.get("meta", {})
    for key in META_REQUIRED:
        assert key in meta, f"[{filename}] meta 缺少 '{key}'"
    assert isinstance(meta.get("baud_rate"), (int, float)), \
        f"[{filename}] meta.baud_rate 不是数字"
    assert meta["baud_rate"] > 0, f"[{filename}] meta.baud_rate 应 > 0"


# ═══════════════════════════════════════════════
#  can_id_schema 段校验
# ═══════════════════════════════════════════════

CAN_ID_FIELD_REQUIRED = ["name", "bit_start", "bit_len"]


@pytest.mark.parametrize("filename", PROTO_FILES)
def test_can_id_schema_structure(filename):
    """can_id_schema 字段结构正确"""
    data = _load_json(filename)
    schema = data.get("can_id_schema", {})
    assert "total_bits" in schema, f"[{filename}] can_id_schema 缺少 total_bits"
    assert isinstance(schema["total_bits"], int), f"[{filename}] total_bits 不是整数"
    assert schema["total_bits"] in (11, 29), \
        f"[{filename}] total_bits={schema['total_bits']}, 期望 29 (扩展帧)"

    fields = schema.get("fields", [])
    assert len(fields) >= 2, f"[{filename}] can_id_schema.fields 至少需要 2 个字段"

    for i, f in enumerate(fields):
        for key in CAN_ID_FIELD_REQUIRED:
            assert key in f, f"[{filename}] can_id_schema.fields[{i}] 缺少 '{key}'"
        assert isinstance(f["bit_start"], int), \
            f"[{filename}] fields[{i}].bit_start 不是整数"
        assert isinstance(f["bit_len"], int), \
            f"[{filename}] fields[{i}].bit_len 不是整数"
        assert f["bit_len"] >= 1, \
            f"[{filename}] fields[{i}].bit_len={f['bit_len']} 应 >= 1"
        assert f["bit_start"] + f["bit_len"] <= schema["total_bits"], \
            f"[{filename}] fields[{i}] '{f['name']}' 越界 (bit {f['bit_start']}+{f['bit_len']} > {schema['total_bits']})"

    # 检查 identifier_field 存在
    assert "message_identifier" in schema, f"[{filename}] can_id_schema 缺少 message_identifier"
    assert "identifier_field" in schema, f"[{filename}] can_id_schema 缺少 identifier_field"


# ═══════════════════════════════════════════════
#  message_matcher 段校验
# ═══════════════════════════════════════════════

VALID_MATCHER_TYPES = ("pf_based", "command_number", "data_field")


@pytest.mark.parametrize("filename", PROTO_FILES)
def test_message_matcher(filename):
    """message_matcher 类型合法"""
    data = _load_json(filename)
    matcher = data.get("message_matcher", {})
    assert "type" in matcher, f"[{filename}] message_matcher 缺少 type"
    assert matcher["type"] in VALID_MATCHER_TYPES, \
        f"[{filename}] message_matcher.type='{matcher['type']}' 不合法, 允许: {VALID_MATCHER_TYPES}"
    assert "match_field" in matcher, f"[{filename}] message_matcher 缺少 match_field"


# ═══════════════════════════════════════════════
#  messages 段校验
# ═══════════════════════════════════════════════

MSG_REQUIRED = ["name", "abbr", "identifier", "fields"]
FIELD_REQUIRED = ["name", "byte_start", "length"]
VALID_DATA_TYPES = ("int_le", "int_be", "float_ieee754", "bits", "bcd", "ascii")


@pytest.mark.parametrize("filename", PROTO_FILES)
def test_messages_structure(filename):
    """每条报文应包含全部必需字段"""
    data = _load_json(filename)
    messages = data.get("messages", [])
    assert len(messages) >= 1, f"[{filename}] messages 不能为空"

    for i, msg in enumerate(messages):
        prefix = f"[{filename}] messages[{i}]"
        for key in MSG_REQUIRED:
            assert key in msg, f"{prefix} 缺少 '{key}'"
        assert msg["name"].strip(), f"{prefix} name 不能为空"
        assert msg["abbr"].strip(), f"{prefix} abbr 不能为空"
        assert isinstance(msg.get("data_length"), (int, type(None))), \
            f"{prefix} data_length 类型错误"

        for j, field in enumerate(msg.get("fields", [])):
            fpref = f"{prefix} '{msg['abbr']}' fields[{j}]"
            for key in FIELD_REQUIRED:
                assert key in field, f"{fpref} 缺少 '{key}'"
            assert field["name"].strip(), f"{fpref} name 不能为空"
            assert isinstance(field["byte_start"], int), f"{fpref} byte_start 不是整数"
            assert field["byte_start"] >= 1, f"{fpref} byte_start={field['byte_start']} 应从 1 开始"
            assert isinstance(field["length"], int), f"{fpref} length 不是整数"
            assert field["length"] >= 1, f"{fpref} length={field['length']} 应 >= 1"

            dt = field.get("data_type", "int_le")
            assert dt in VALID_DATA_TYPES, \
                f"{fpref} data_type='{dt}' 不合法, 允许: {VALID_DATA_TYPES}"

            # 位域字段特殊检查
            if dt == "bits":
                assert "bit_start" in field, f"{fpref} bits 类型需要 bit_start"
                assert "bit_len" in field, f"{fpref} bits 类型需要 bit_len"
                assert field["bit_len"] <= 8, \
                    f"{fpref} bit_len={field['bit_len']} 不应超过 8 (单字节位域)"

            # 浮点字段特殊检查
            if dt == "float_ieee754":
                assert field["length"] == 4, \
                    f"{fpref} float_ieee754 要求 length=4, 实际 {field['length']}"

            # 枚举键应为数字（JSON 只支持字符串键，解析时转换）
            if "enum" in field:
                for ek in field["enum"]:
                    try:
                        int(ek)
                    except ValueError:
                        pytest.fail(
                            f"{fpref} enum 键 '{ek}' 应为数字字符串, "
                            f"如 {{\"0\": \"关机\", \"1\": \"开机\"}}"
                        )


# ═══════════════════════════════════════════════
#  message_groups 段校验
# ═══════════════════════════════════════════════

@pytest.mark.parametrize("filename", PROTO_FILES)
def test_message_groups_structure(filename):
    """message_groups 格式正确"""
    data = _load_json(filename)
    groups = data.get("message_groups", [])
    for i, group in enumerate(groups):
        prefix = f"[{filename}] message_groups[{i}]"
        assert "name" in group, f"{prefix} 缺少 name"
        assert group["name"].strip(), f"{prefix} name 不能为空"
        assert "messages" in group, f"{prefix} 缺少 messages"
        assert isinstance(group["messages"], list), f"{prefix} messages 不是数组"


# ═══════════════════════════════════════════════
#  跨文件一致性
# ═══════════════════════════════════════════════

def test_all_files_valid_json():
    """四份 JSON 文件都能被合法解析"""
    for filename in PROTO_FILES:
        data = _load_json(filename)
        assert isinstance(data, dict), f"{filename} 不是 JSON 对象"


def test_protocol_ids_unique():
    """四个协议的 protocol_id 应互不相同"""
    ids = []
    for filename in PROTO_FILES:
        data = _load_json(filename)
        pid = data["meta"]["protocol_id"]
        assert pid not in ids, f"protocol_id '{pid}' 重复"
        ids.append(pid)


def test_all_have_addresses():
    """所有协议应定义地址表"""
    for filename in PROTO_FILES:
        data = _load_json(filename)
        addrs = data.get("addresses", {})
        assert len(addrs) >= 1, f"[{filename}] addresses 不能为空"
