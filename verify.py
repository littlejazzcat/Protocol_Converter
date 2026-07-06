"""验证四套协议的编解码功能"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.loader import load_protocol, validate_integrity
from services.query_engine import QueryEngine
from services.can_codec import CanCodec

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

PROTO_FILES = [
    ("gbt27930_v1.1.json", "BCL", {"车辆接口充电电压需求": 420.0, "车辆接口充电电流需求": -45.0, "充电模式": "恒流充电"}),
    ("anshibo_1k040b.json", "CMD_00_RESP", None),  # decode only (nibble issue)
    ("sg_unified_v107.json", "RC_CMD_FIXED", {"操作指令": "快速开机", "输出电压范围": "低压段(200-500V)", "功分接触器": "分断", "主接触器": "分断", "分组编码": 0, "给定电压": 100.0, "给定电流": 10.0, "电池电压": 200.0}),
    ("infypower_v107.json", "CMD_08_SYS_INT", {"系统总电压": 500000, "系统总电流": 60000}),
]

DECODE_TESTS = [
    ("gbt27930_v1.1.json", "BCL", "68 10 DE 0D 02"),
    ("gbt27930_v1.1.json", "BHM", "43 0E"),
    ("anshibo_1k040b.json", "CMD_00_RESP", "13 00 00 00 00 07 41 9E"),
    ("sg_unified_v107.json", "RC_CMD_FIXED", "01 00 E8 03 E8 03 D0 07"),
    ("infypower_v107.json", "CMD_08_SYS_INT", "00 07 A1 20 00 00 EA 60"),
    ("infypower_v107.json", "CMD_01_SYS_FLOAT", "43 FA 00 00 42 48 00 00"),
]

print("=" * 60)
print("Protocol Converter — 编解码功能验证")
print("=" * 60)

for fid, abbr, params in PROTO_FILES:
    proto = load_protocol(os.path.join(DATA_DIR, fid))
    q = QueryEngine(proto)
    c = CanCodec(proto)
    msg = q.by_abbr(abbr)
    name = proto.meta["protocol_name"]
    mid = msg.identifier

    # 完整性校验
    errors = validate_integrity(proto)
    status = "OK" if not errors else f"ERR({len(errors)})"

    print(f"\n{'─' * 60}")
    print(f"协议: {name} [{status}]")
    print(f"报文: {msg.abbr} — {msg.name}")
    print(f"标识: {mid}")
    print(f"字段数: {len(msg.fields)}, 可编辑: {sum(1 for f in msg.fields if f.editable)}")

    # 编码测试（跳过安世博）
    if params and fid != "anshibo_1k040b.json":
        result = c.encode(msg, params)
        print(f"编码: {params}")
        print(f"  → CAN ID: {result['can_id_hex']}  数据: {result['data_hex']}")
        # 解码验证
        decoded = c.decode(msg, result["data"])
        print(f"解码验证: {decoded}")

print(f"\n{'─' * 60}")
print("解码功能验证:")
for fid, abbr, data_hex in DECODE_TESTS:
    proto = load_protocol(os.path.join(DATA_DIR, fid))
    q = QueryEngine(proto)
    c = CanCodec(proto)
    msg = q.by_abbr(abbr)
    data = bytes.fromhex(data_hex.replace(" ", ""))
    result = c.decode(msg, data)
    print(f"  {abbr} ({data_hex})")
    for k, v in result.items():
        if isinstance(v, dict):
            print(f"    {k}: {v['label']} (value={v['value']})")
        else:
            print(f"    {k}: {v}")
    print()

print("=" * 60)
print("验证完成")
print("=" * 60)
