"""报文编码面板 — 输入物理量 → 生成 CAN 帧"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QComboBox, QLineEdit, QLabel, QPushButton, QTextEdit, QScrollArea,
    QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from services.query_engine import QueryEngine
from services.can_codec import CanCodec
from models.protocol import MessageDef


class EncodePanel(QWidget):
    """编码面板：选报文 → 填参数 → 生成 CAN 帧"""

    def __init__(self, query_engine: QueryEngine, codec: CanCodec):
        super().__init__()
        self.query = query_engine
        self.codec = codec
        self._current_msg: MessageDef = None
        self._input_widgets = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── 报文选择 ──
        select_layout = QHBoxLayout()
        select_layout.addWidget(QLabel("选择报文:"))
        self.msg_combo = QComboBox()
        self.msg_combo.setMinimumWidth(300)
        # 按阶段分组填充
        for group in self.query.protocol.message_groups:
            group_name = group.get("name", "")
            for abbr in group.get("messages", []):
                msg = self.query.by_abbr(abbr)
                if msg:
                    self.msg_combo.addItem(f"{msg.abbr} — {msg.name} [{group_name}]", msg)
        self.msg_combo.currentIndexChanged.connect(self._on_msg_changed)
        select_layout.addWidget(self.msg_combo)
        select_layout.addStretch()
        layout.addLayout(select_layout)

        # ── 身份信息（只读） ──
        self.identity_label = QLabel("")
        self.identity_label.setWordWrap(True)
        self.identity_label.setStyleSheet("background: #f5f5f5; padding: 6px; border: 1px solid #ddd; border-radius: 3px; font-family: Consolas; font-size: 11px;")
        self.identity_label.setVisible(False)
        layout.addWidget(self.identity_label)

        # ── 输入区域（可滚动） ──
        input_group = QGroupBox("参数输入")
        input_outer = QVBoxLayout(input_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.input_container = QWidget()
        self.input_layout = QFormLayout(self.input_container)
        self.input_layout.setLabelAlignment(Qt.AlignRight)
        scroll.setWidget(self.input_container)
        input_outer.addWidget(scroll)

        layout.addWidget(input_group)

        # ── 生成按钮 ──
        btn_layout = QHBoxLayout()
        self.encode_btn = QPushButton("生成 CAN 帧")
        self.encode_btn.setMinimumHeight(36)
        self.encode_btn.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.encode_btn.clicked.connect(self._on_encode)
        btn_layout.addWidget(self.encode_btn)

        self.copy_id_btn = QPushButton("复制 CAN ID")
        self.copy_id_btn.clicked.connect(self._copy_can_id)
        btn_layout.addWidget(self.copy_id_btn)

        self.copy_data_btn = QPushButton("复制数据域")
        self.copy_data_btn.clicked.connect(self._copy_data)
        btn_layout.addWidget(self.copy_data_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # ── 结果预览 ──
        result_group = QGroupBox("生成结果")
        result_layout = QVBoxLayout(result_group)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(300)
        self.result_text.setFont(QFont("Consolas", 12))
        result_layout.addWidget(self.result_text)
        layout.addWidget(result_group)

        # 初始化第一条报文
        if self.msg_combo.count() > 0:
            self._on_msg_changed(0)

    def _on_msg_changed(self, index: int):
        """切换报文 → 重建输入表单"""
        msg = self.msg_combo.currentData()
        if msg is None:
            return
        self._current_msg = msg
        self._input_widgets.clear()
        self.result_text.clear()

        # 身份信息
        id_info = []
        id_fields = [f for f in msg.fields if not f.editable]
        if id_fields:
            id_info.append(f"<b>{msg.abbr} — {msg.name}</b>")
            for f in id_fields:
                val = f.default_value if f.default_value is not None else "—"
                id_info.append(f"  {f.name}: <b>{val}</b>")
            self.identity_label.setText("<br>".join(id_info))
            self.identity_label.setVisible(True)
        else:
            self.identity_label.setVisible(False)

        # 清除旧表单
        while self.input_layout.rowCount() > 0:
            self.input_layout.removeRow(0)

        # 仅为可编辑字段创建输入控件
        editable_fields = [f for f in msg.fields if f.editable]
        for field in editable_fields:
            if field.enum:
                # 枚举 → 下拉框
                combo = QComboBox()
                for k, v in field.enum.items():
                    combo.addItem(v, k)
                combo.setMinimumWidth(200)
                self.input_layout.addRow(f"{field.name}:", combo)
                self._input_widgets[field.name] = combo
            elif field.data_type == "bcd":
                # BCD → 文本输入
                edit = QLineEdit()
                edit.setPlaceholderText("例: 13 20 15 11 10 20 19")
                edit.setMinimumWidth(200)
                edit.setFont(QFont("Consolas", 10))
                self.input_layout.addRow(f"{field.name}:", edit)
                self._input_widgets[field.name] = edit
            elif field.data_type == "ascii":
                # ASCII → 文本输入
                edit = QLineEdit()
                edit.setPlaceholderText("ASCII 文本")
                edit.setMinimumWidth(200)
                self.input_layout.addRow(f"{field.name}:", edit)
                self._input_widgets[field.name] = edit
            else:
                # 数值 → 数字输入
                edit = QLineEdit()
                hint = ""
                suffix = f" {field.unit}" if field.unit else ""
                if field.range_min is not None and field.range_max is not None:
                    hint = f"范围: {field.range_min}~{field.range_max}{suffix}"
                edit.setPlaceholderText(hint)
                edit.setMinimumWidth(200)
                self.input_layout.addRow(f"{field.name}:", edit)
                self._input_widgets[field.name] = edit

    def _on_encode(self):
        """执行编码"""
        if self._current_msg is None:
            return

        params = {}
        for field in self._current_msg.fields:
            if not field.editable:
                continue
            widget = self._input_widgets.get(field.name)
            if widget is None:
                continue

            if isinstance(widget, QComboBox):
                value = widget.currentData()
                if value is not None:
                    params[field.name] = int(value)
            else:
                text = widget.text().strip()
                if not text:
                    if field.required:
                        QMessageBox.warning(self, "参数缺失", f"必填字段 '{field.name}' 未填写")
                        return
                    continue
                try:
                    if field.data_type in ("bcd", "ascii"):
                        params[field.name] = text
                    else:
                        params[field.name] = float(text)
                except ValueError:
                    QMessageBox.warning(self, "格式错误", f"字段 '{field.name}' 值 '{text}' 不是有效数字")
                    return

        try:
            result = self.codec.encode(self._current_msg, params)
            self._last_result = result
            if result.get("tp"):
                lines = [f"完整数据 ({len(result['data'])}B):  {result['data_hex']}", "", f"--- TP 分包 ({len(result['tp_frames'])} 帧) ---"]
                for f in result["tp_frames"]:
                    lines.append(f"  [{f['type']}] ID={f['can_id_hex']}  DATA={f['data_hex']}")
                self.result_text.setPlainText("\n".join(lines))
            else:
                self.result_text.setPlainText(
                    f"CAN ID:  {result['can_id_hex']}\n"
                    f"数据域:  {result['data_hex']}"
                )
        except Exception as e:
            QMessageBox.critical(self, "编码失败", str(e))

    def _copy_can_id(self):
        if hasattr(self, "_last_result"):
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(self._last_result["can_id_hex"])

    def _copy_data(self):
        if hasattr(self, "_last_result"):
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(self._last_result["data_hex"])
