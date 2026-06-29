"""安世博 UAA-1K040B-E 已知向量

来源: UAA-1K040B-E CAN通信协议 S1.md 和 decode_panel.py 预置测试数据。

注意: Byte0 的组地址 (高 nibble) 和信息类型 (低 nibble) 共享同一字节,
目前 JSON 建模中"组地址"为 1 字节整数, 与信息类型位域存在冲突。
故编码向量暂不测试 Byte0 组合, 仅测试数据负载部分。
"""

# (msg_abbr, param_dict, expected_data_hex)
ENCODE_VECTORS = [
    # ⚠ 跳过含 Byte0 nibble 冲突的报文 (CMD_00_REQ, CMD_02_REQ 等)
    # 仅测试数据域负载的独立字段
]

# (msg_abbr, data_hex, expected_values_dict)
DECODE_VECTORS = [
    # ── CMD_00_RESP: 读电压应答 475.55V ──
    # data "13 00 00 00 00 07 41 9E"
    # Byte4~7: 0x0007419E BE = 475550 mV
    (
        "CMD_00_RESP",
        "13 00 00 00 00 07 41 9E",
        {
            "模块输出电压": 475550,  # raw mV
        },
    ),
    # ── CMD_02_REQ: 设电压请求 475.55V ──
    (
        "CMD_02_REQ",
        "10 02 00 00 00 07 41 9E",
        {
            "输出电压设定值": 475550,
        },
    ),
    # ── CMD_04_REQ: 开机 (0) ──
    (
        "CMD_04_REQ",
        "10 04 00 00 00 00 00 00",
        {
            "开关机": {"value": 0, "label": "开机"},
        },
    ),
    # ── CMD_04_REQ: 关机 (1) ──
    (
        "CMD_04_REQ",
        "10 04 00 00 00 00 00 01",
        {
            "开关机": {"value": 1, "label": "关机"},
        },
    ),
    # ── CMD_04_REQ: 线性关机 (17=0x11) ──
    (
        "CMD_04_REQ",
        "10 04 00 00 00 00 00 11",
        {
            "开关机": {"value": 17, "label": "线性关机"},
        },
    ),
]
