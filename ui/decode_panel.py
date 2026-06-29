"""单帧解码面板 — 输入 CAN ID + 数据域 Hex, 输出解码结果"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLineEdit, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QHeaderView, QSplitter
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from services.query_engine import QueryEngine
from services.can_codec import CanCodec


class DecodePanel(QWidget):
    """解码面板：单帧 CAN 数据解码"""

    def __init__(self, query_engine: QueryEngine, codec: CanCodec):
        super().__init__()
        self.query = query_engine
        self.codec = codec
        self._protocol_id = query_engine.protocol.meta.get("protocol_id", "")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── 输入区 ──
        input_group = QGroupBox("CAN 帧输入")
        input_layout = QHBoxLayout(input_group)

        input_layout.addWidget(QLabel("CAN ID (Hex):"))
        self.can_id_input = QLineEdit()
        self.can_id_input.setPlaceholderText("例: 181056F4")
        self.can_id_input.setMinimumWidth(150)
        self.can_id_input.setFont(QFont("Consolas", 11))
        self.can_id_input.returnPressed.connect(self._on_decode)
        input_layout.addWidget(self.can_id_input)

        input_layout.addWidget(QLabel("数据域 (Hex):"))
        self.data_input = QTextEdit()
        self.data_input.setPlaceholderText("单帧: 68 10 DE 0D 02    TP模式: 每行一帧")
        self.data_input.setMinimumWidth(280)
        self.data_input.setMaximumHeight(55)
        self.data_input.setFont(QFont("Consolas", 11))
        self.data_input.setTabChangesFocus(True)
        input_layout.addWidget(self.data_input)

        self.tp_checkbox = QPushButton("TP")
        self.tp_checkbox.setCheckable(True)
        self.tp_checkbox.setToolTip("TP 重组模式: 输入多帧 TP.DT 数据,每行一帧")
        self.tp_checkbox.setFixedWidth(36)
        self.tp_checkbox.setStyleSheet("QPushButton { font-size: 10px; padding: 2px; } QPushButton:checked { background: #3498db; color: white; font-weight: bold; }")
        self.tp_checkbox.toggled.connect(self._on_tp_toggled)
        input_layout.addWidget(self.tp_checkbox)

        self.decode_btn = QPushButton("解码")
        self.decode_btn.setMinimumWidth(80)
        self.decode_btn.clicked.connect(self._on_decode)
        input_layout.addWidget(self.decode_btn)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self._on_clear)
        input_layout.addWidget(self.clear_btn)

        layout.addWidget(input_group)

        # ── 快捷输入按钮 ──
        quick_group = QGroupBox("快速测试数据")
        quick_layout = QHBoxLayout(quick_group)

        presets = self._get_presets()

        for label, can_id, data in presets:
            btn = QPushButton(label)
            btn.setToolTip(f"CAN ID: {can_id}\nData: {data}")
            btn.clicked.connect(lambda checked, cid=can_id, d=data: self._set_preset(cid, d))
            quick_layout.addWidget(btn)

        quick_layout.addStretch()
        layout.addWidget(quick_group)

        # ── 结果区 ──
        result_group = QGroupBox("解码结果")
        result_layout = QVBoxLayout(result_group)

        # CAN ID 概要信息
        self.can_id_summary = QLabel()
        self.can_id_summary.setStyleSheet("font-family: Consolas; font-size: 12px; font-weight: bold; padding: 4px;")
        self.can_id_summary.setVisible(False)
        result_layout.addWidget(self.can_id_summary)

        # 识别信息
        self.id_info_toggle = QPushButton("▼ CAN ID 解析详情")
        self.id_info_toggle.setStyleSheet("text-align: left; padding: 2px 4px; font-size: 11px;")
        self.id_info_toggle.clicked.connect(self._toggle_id_info)
        self.id_info_toggle.setVisible(False)
        result_layout.addWidget(self.id_info_toggle)

        self.id_info = QTextEdit()
        self.id_info.setReadOnly(True)
        self.id_info.setMaximumHeight(100)
        self.id_info.setFont(QFont("Consolas", 10))
        result_layout.addWidget(self.id_info)

        # CAN ID 位域展开
        self.can_id_toggle = QPushButton("▶ CAN ID 位域详情")
        self.can_id_toggle.setStyleSheet("text-align: left; padding: 4px; font-size: 11px;")
        self.can_id_toggle.clicked.connect(self._toggle_can_id_detail)
        self.can_id_toggle.setVisible(False)
        result_layout.addWidget(self.can_id_toggle)

        self.can_id_detail = QWidget()
        self.can_id_detail.setVisible(False)
        self.can_id_layout = QVBoxLayout(self.can_id_detail)
        self.can_id_layout.setContentsMargins(0, 0, 0, 0)
        self.can_id_bar = QWidget()
        self.can_id_bar_layout = QHBoxLayout(self.can_id_bar)
        self.can_id_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.can_id_bar_layout.setSpacing(0)
        self.can_id_layout.addWidget(self.can_id_bar)
        self.can_id_legend = QLabel()
        self.can_id_legend.setWordWrap(True)
        self.can_id_legend.setStyleSheet("font-family: Consolas; font-size: 10px;")
        self.can_id_layout.addWidget(self.can_id_legend)
        result_layout.addWidget(self.can_id_detail)

        # 解码表格
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(5)
        self.result_table.setHorizontalHeaderLabels(["字段", "SPN", "字节位置", "原始值(Hex)", "物理量"])
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        result_layout.addWidget(self.result_table)

        layout.addWidget(result_group)

    def _on_tp_toggled(self, checked):
        if checked:
            self.data_input.setMaximumHeight(120)
            self.data_input.setPlaceholderText("TP 重组: 每行一帧 TP.DT 数据\n例:\n10 0D A1 01 DE 0D B0 00\n02 68 10 20 68 10 17 70")
        else:
            self.data_input.setMaximumHeight(55)
            self.data_input.setPlaceholderText("单帧: 68 10 DE 0D 02    TP模式: 每行一帧")

    def _on_decode(self):
        """执行解码（协议无关）"""
        self.result_table.setRowCount(0)
        self.id_info.clear()

        can_id_text = self.can_id_input.text().strip().replace("0x", "").replace(" ", "")
        data_text = self.data_input.toPlainText().strip()

        if not can_id_text or not data_text:
            self.id_info.setPlainText("请输入 CAN ID 和数据域")
            return

        try:
            can_id = int(can_id_text, 16)
        except ValueError:
            self.id_info.setPlainText(f"CAN ID 格式错误: {can_id_text}")
            return

        # 解析数据
        try:
            if self.tp_checkbox.isChecked():
                # TP 模式: 每行一帧
                lines = [l.strip() for l in data_text.split("\n") if l.strip()]
                frames = [bytes.fromhex(l.replace(" ", "")) for l in lines]
                data_bytes = self.codec.tp_reassemble(frames)
                tp_note = f"TP 重组: {len(lines)} 帧 → {len(data_bytes)} 字节"
            else:
                data_hex = data_text.replace(" ", "").replace("0x", "").replace("\n", "")
                data_bytes = bytes.fromhex(data_hex)
                tp_note = ""
        except ValueError:
            self.id_info.setPlainText("数据域格式错误，请输入 Hex 字符串")
            return

        # 解析 CAN ID（协议无关）
        id_info = self.query.parse_can_id(can_id)
        id_lines = [f"CAN ID: 0x{can_id:08X}"]
        for f in self.query.protocol.can_id_schema.fields:
            val = id_info.get(f.name, "?")
            id_lines.append(f"  {f.name}: {id_info.get(f'{f.name}_hex', val)} ({f.description})")

        # 匹配报文（协议无关）
        msg = self.query.by_can_id(can_id, data_bytes)
        if msg is None:
            self.id_info.setPlainText("\n".join(id_lines) + "\n\n⚠ 未找到匹配报文")
            return

        id_lines.append(f"\n报文: {msg.abbr} — {msg.name}")
        # 动态判断方向（安世博通过 MessageType 区分请求/应答）
        direction = self._get_direction(msg, can_id, data_bytes, id_info)
        if direction:
            id_lines.append(f"方向: {direction}")
        elif msg.direction:
            id_lines.append(f"方向: {msg.direction}")
        if msg.cycle_ms:
            id_lines.append(f"周期: {msg.cycle_ms}ms")
        if tp_note:
            id_lines.append(tp_note)
        self.id_info.setPlainText("\n".join(id_lines))
        self.can_id_summary.setText(f"CAN ID: 0x{can_id:08X}  →  {msg.abbr} — {msg.name}")
        self.can_id_summary.setVisible(True)
        self.id_info_toggle.setVisible(True)
        self.id_info.setMaximumHeight(16777215)
        self.id_info_toggle.setText("▼ CAN ID 解析详情")

        # 解码
        result = self.codec.decode(msg, data_bytes)

        # 渲染 CAN ID 位域可视化
        self._render_can_id_bar(can_id, id_info)

        # 填充表格
        self._populate_result(msg, data_bytes, result)

    def _populate_result(self, msg, data_bytes: bytes, result: dict):
        """填充解码结果表格"""
        self.result_table.setRowCount(len(msg.fields))
        for i, field in enumerate(msg.fields):
            self.result_table.setItem(i, 0, QTableWidgetItem(field.name))
            self.result_table.setItem(i, 1, QTableWidgetItem(str(field.spn) if field.spn else "-"))

            # 字节位置
            pos = f"Byte{field.byte_start}"
            if field.bit_start is not None:
                pos += f".{field.bit_start}"
            self.result_table.setItem(i, 2, QTableWidgetItem(pos))

            # 原始值
            try:
                raw = self._extract_raw(data_bytes, field)
                self.result_table.setItem(i, 3, QTableWidgetItem(raw))
            except Exception:
                self.result_table.setItem(i, 3, QTableWidgetItem("N/A"))

            # 物理量
            value = result.get(field.name, "N/A")
            display = self._format_value(value, field)
            self.result_table.setItem(i, 4, QTableWidgetItem(display))

    def _extract_raw(self, data: bytes, field) -> str:
        """提取字段原始 Hex"""
        start = field.byte_start - 1
        if field.data_type == "bits":
            byte_val = data[start]
            mask = ((1 << field.bit_len) - 1) << field.bit_start
            raw = (byte_val & mask) >> field.bit_start
            return f"0x{raw:02X} ({raw})"
        else:
            chunk = data[start:start + field.length]
            return chunk.hex(" ").upper()

    def _format_value(self, value, field) -> str:
        """格式化显示值"""
        if isinstance(value, dict) and "label" in value:
            return f"{value['label']}"
        if isinstance(value, float):
            unit = field.unit or ""
            return f"{value} {unit}".strip()
        if isinstance(value, int) and field.unit:
            return f"{value} {unit}"
        return str(value)

    def _set_preset(self, can_id: str, data: str):
        """设置预置测试数据"""
        self.can_id_input.setText(can_id)
        self.data_input.setPlainText(data)
        # 自动检测 TP 模式: 数据含换行则开启
        if "\n" in data:
            self.tp_checkbox.setChecked(True)
            self.data_input.setMaximumHeight(120)
        else:
            self.tp_checkbox.setChecked(False)
            self.data_input.setMaximumHeight(55)
        self._on_decode()

    def _get_direction(self, msg, can_id: int, data: bytes, id_info: dict) -> str:
        """根据协议动态判断报文方向"""
        matcher = self.query.protocol.message_matcher

        # 安世博: MessageType 低 nibble 决定请求/应答
        if matcher.type == "data_field" and len(data) > 0:
            msg_type = data[0] & 0x0F
            type_names = {0x00: "SetData", 0x01: "SetDataResponse", 0x02: "ReadData",
                          0x03: "ReadDataResponse", 0x04: "ReadSerialNumberResponse"}
            type_name = type_names.get(msg_type, f"0x{msg_type:02X}")
            if msg_type in (0x00, 0x02):  # 请求
                mod_addr = id_info.get("module_address", "?")
                mon_addr = id_info.get("monitor_address", "?")
                return f"监控(0x{mon_addr:02X}) → 模块(0x{mod_addr:02X}) [{type_name}请求]"
            else:  # 应答
                mod_addr = id_info.get("module_address", "?")
                mon_addr = id_info.get("monitor_address", "?")
                return f"模块(0x{mod_addr:02X}) → 监控(0x{mon_addr:02X}) [{type_name}应答]"

        # 英飞源: command_number + device_number 方式，根据 dest/source 地址判断
        if matcher.type == "command_number":
            dst = id_info.get("dest_addr", 0)
            src = id_info.get("source_addr", 0)
            if dst == 0xF0 or dst in range(0xF0, 0xF9):
                return f"模块(0x{src:02X}) → 监控(0x{dst:02X}) [应答]"
            else:
                return f"监控(0x{src:02X}) → 模块(0x{dst:02X}) [请求]"

        return ""

    def _get_presets(self):
        """根据协议 ID 返回预置测试数据"""
        pid = self._protocol_id
        if pid == "gbt27930_v1.1":
            return [
                ("BCL 420V/-45A/恒流", "181056F4", "68 10 DE 0D 02"),
                ("BCS 420V/SOC80%/60min", "1C1156F4", "68 10 DE 0D 04 00 50 3C 00"),
                ("BHM 365.1V", "182756F4", "43 0E"),
                ("CHM V1.1", "1826F456", "01 01 00"),
                ("BRO 准备好", "100956F4", "AA"),
                ("CRM 已辨识 #1", "1801F456", "AA 01 00 00 00 20 20 20"),
                ("CCS 420V/允许", "1812F456", "68 10 DE 0D 0F 00 01"),
                ("BSM 正常", "181356F4", "01 20 01 10 02 00 40"),
                ("CRO 准备好", "100AF456", "AA"),
                ("BCP [TP] 4.17V/-45A/17.6%", "1C0656F4", "10 0D A1 01 DE 0D B0 00\n02 68 10 20 68 10 17 70"),
                ("BCS [TP] 420V/SOC80%", "1C1156F4", "10 09 68 10 DE 0D 04 00\n02 50 3C 00 FF FF FF FF"),
            ]
        elif pid == "anshibo_1k040b":
            return [
                ("CMD_00 读电压[应答] 475.55V", "08200000", "13 00 00 00 00 07 41 9E"),
                ("CMD_00 读电压[请求]", "08200000", "12 00 00 00 00 00 00 00"),
                ("CMD_02 设电压[请求] 475.55V", "08200000", "10 02 00 00 00 07 41 9E"),
                ("CMD_02 设电压[应答] 475.55V", "08200000", "11 02 00 00 00 07 41 9E"),
                ("CMD_04 开机[请求]", "08200000", "10 04 00 00 00 00 00 00"),
                ("CMD_04 关机[请求]", "08200000", "10 04 00 00 00 00 00 01"),
                ("CMD_04 线性关机[请求]", "08200000", "10 04 00 00 00 00 00 11"),
            ]
        elif pid == "sg_unified_v107":
            return [
                ("遥控命令 500V/30A/低压/开机", "0C010000", "11 00 F4 01 B8 0B 00 00"),
                ("遥信遥测 500V/30A", "08200000", "80 00 F4 01 B8 0B 01 00"),
            ]
        elif pid == "infypower_v107":
            return [
                ("CMD_01 系统500V/50A(浮点)", "02813FF0", "43 FA 00 00 42 48 00 00"),
                ("CMD_08 系统500V/60A(定点)", "02883FF0", "00 07 A1 20 00 00 EA 60"),
                ("CMD_09 模块200V/5A(定点)", "028900F0", "00 03 0D 40 00 00 13 88"),
                ("CMD_1A 开机", "029A3FF0", "00 00 00 00 00 00 00 00"),
                ("CMD_1B 设300V/10A", "029B3FF0", "00 04 93 E0 00 00 27 10"),
            ]
        return []

    def _on_clear(self):
        self.can_id_input.clear()
        self.data_input.clear()
        self.tp_checkbox.setChecked(False)
        self.result_table.setRowCount(0)
        self.id_info.clear()
        self.id_info_toggle.setVisible(False)
        self.can_id_summary.setVisible(False)
        self.can_id_detail.setVisible(False)
        self.can_id_toggle.setVisible(False)
        self.id_info.setVisible(True)
        self.id_info.setMaximumHeight(16777215)

    def _toggle_id_info(self):
        if self.id_info.maximumHeight() < 200:
            self.id_info.setMaximumHeight(16777215)
            self.id_info_toggle.setText("▼ CAN ID 解析详情")
        else:
            self.id_info.setMaximumHeight(100)
            self.id_info_toggle.setText("▶ CAN ID 解析详情")

    def _toggle_can_id_detail(self):
        visible = not self.can_id_detail.isVisible()
        self.can_id_detail.setVisible(visible)
        self.can_id_toggle.setText("▼ CAN ID 位域详情" if visible else "▶ CAN ID 位域详情")

    def _render_can_id_bar(self, can_id: int, id_info: dict):
        """渲染 CAN ID 29-bit 位域色条"""
        # 清除旧内容
        while self.can_id_bar_layout.count():
            item = self.can_id_bar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        schema = self.query.protocol.can_id_schema
        colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c", "#e67e22", "#95a5a6"]

        legend_parts = []
        total_bits = schema.total_bits

        # 按 bit_start 从高到低排序
        sorted_fields = sorted(schema.fields, key=lambda f: f.bit_start, reverse=True)

        for i, f in enumerate(sorted_fields):
            val = id_info.get(f.name, 0)
            color = colors[i % len(colors)]
            width_pct = f.bit_len / total_bits * 100

            seg = QLabel()
            seg.setFixedHeight(24)
            seg.setMinimumWidth(max(int(width_pct * 6), 30))
            seg.setStyleSheet(
                f"background: {color}; color: white; font-family: Consolas; "
                f"font-size: 9px; padding: 2px; border: 1px solid #333;"
                f"border-radius: 2px; margin: 0;"
            )
            seg.setAlignment(Qt.AlignCenter)
            seg.setToolTip(f"{f.name}: 0x{val:0{(f.bit_len + 3) // 4}X} ({val})\n{f.description}")
            hex_w = max(f.bit_len // 4, 1)
            seg.setText(f"0x{val:0{hex_w}X}")
            self.can_id_bar_layout.addWidget(seg, int(width_pct * 10))

            legend_parts.append(
                f"<span style='color:{color}; font-weight:bold;'>■ {f.name}</span>"
                f"({f.bit_len}bit)=0x{val:0{(f.bit_len + 3) // 4}X}"
            )

        self.can_id_bar_layout.addStretch()
        self.can_id_legend.setText(" | ".join(legend_parts))
        self.can_id_toggle.setVisible(True)
        self.can_id_detail.setVisible(True)
        self.can_id_toggle.setText("▼ CAN ID 位域详情")
