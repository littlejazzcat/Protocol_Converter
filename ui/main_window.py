"""主窗口 — 协议选择器 + 查询面板 + 解码面板"""

import os
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QLabel, QComboBox, QHBoxLayout, QStatusBar, QMessageBox
)
from PySide6.QtCore import Qt

from models.loader import load_protocol
from services.query_engine import QueryEngine
from services.can_codec import CanCodec
from ui.query_panel import QueryPanel
from ui.decode_panel import DecodePanel
from ui.encode_panel import EncodePanel


class MainWindow(QMainWindow):
    """Protocol Converter 主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Protocol Converter — GB/T 27930 CAN 报文解析工具")
        self.resize(1100, 750)

        self._protocol = None
        self._query = None
        self._codec = None

        self._setup_ui()
        self._load_default_protocol()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # ── 顶部：协议选择器 ──
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("协议:"))
        self.protocol_combo = QComboBox()
        self.protocol_combo.setMinimumWidth(280)
        self.protocol_combo.addItem("GB/T 27930-2023 A类系统 (V1.1)", "gbt27930_v1.1")
        self.protocol_combo.addItem("安世博 UAA-1K040B-E", "anshibo_1k040b")
        self.protocol_combo.addItem("国网三统一模块 V107", "sg_unified_v107")
        self.protocol_combo.addItem("英飞源充电模块 V107", "infypower_v107")
        self.protocol_combo.setCurrentIndex(0)
        self.protocol_combo.currentIndexChanged.connect(self._on_protocol_changed)
        top_layout.addWidget(self.protocol_combo)

        self.protocol_info_label = QLabel("")
        top_layout.addWidget(self.protocol_info_label)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        # ── 标签页 ──
        self.tab_widget = QTabWidget()
        self.query_panel = None
        self.decode_panel = None
        self.encode_panel = None
        layout.addWidget(self.tab_widget)

        # ── 状态栏 ──
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _load_default_protocol(self):
        """加载默认协议"""
        self._load_protocol_by_id("gbt27930_v1.1")

    def _load_protocol_by_id(self, protocol_id: str):
        """加载指定协议"""
        # 构建路径
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        json_path = os.path.join(base_dir, "data", f"{protocol_id}.json")

        if not os.path.exists(json_path):
            QMessageBox.warning(self, "错误", f"协议文件不存在:\n{json_path}")
            return

        try:
            self._protocol = load_protocol(json_path)
            self._query = QueryEngine(self._protocol)
            self._codec = CanCodec(self._protocol)

            # 更新协议信息
            meta = self._protocol.meta
            baud = meta.get("baud_rate", 0)
            self.protocol_info_label.setText(f"波特率: {baud//1000} kbps | {len(self._protocol.messages)} 条报文")

            # 重建面板
            self._rebuild_panels()

            self.status_bar.showMessage(
                f"已加载: {meta.get('protocol_name', '')} ({meta.get('version', '')}) | "
                f"{len(self._protocol.messages)} 条报文"
            )

        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法加载协议文件:\n{str(e)}")

    def _rebuild_panels(self):
        """重建标签页内容"""
        self.tab_widget.clear()

        if self._query and self._codec:
            self.query_panel = QueryPanel(self._query, self._codec)
            self.decode_panel = DecodePanel(self._query, self._codec)
            self.encode_panel = EncodePanel(self._query, self._codec)

            self.tab_widget.addTab(self.query_panel, "📋 报文查询")
            self.tab_widget.addTab(self.decode_panel, "🔍 单帧解码")
            self.tab_widget.addTab(self.encode_panel, "✏️ 报文编码")

            # 从查询面板选择报文 → 自动填充到编码面板
            self.query_panel.message_selected.connect(self._on_message_selected_for_encode)

    def _on_message_selected_for_encode(self, msg):
        """查询面板选中报文后，切换到编码面板并自动选中对应报文"""
        if self.encode_panel and msg:
            for i in range(self.encode_panel.msg_combo.count()):
                if self.encode_panel.msg_combo.itemData(i) is msg:
                    self.encode_panel.msg_combo.setCurrentIndex(i)
                    self.tab_widget.setCurrentWidget(self.encode_panel)
                    break

    def _on_protocol_changed(self, index: int):
        """协议切换"""
        protocol_id = self.protocol_combo.currentData()
        if protocol_id:
            self._load_protocol_by_id(protocol_id)

    def closeEvent(self, event):
        event.accept()
