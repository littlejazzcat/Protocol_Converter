# Protocol Converter v1.1 — 多协议架构设计文档

## 一、项目概述

Protocol Converter 是一个基于 Python 的桌面工具，面向电动汽车充电通信协议生态中的**多协议**工程实践。首期支持四套协议：

| 序号 | 协议 | 角色 | 波特率 | 特点 |
|------|------|------|--------|------|
| 1 | GB/T 27930-2023 A 类系统 | 车桩通信（充电机↔车辆） | 250 kbps | PF 驱动，分辨率/偏移量编码，LE |
| 2 | 安世博 UAA-1K040B-E | 监控↔整流模块 | 125 kbps | CommandType 驱动，4 字节整数，通讯/命令模型 |
| 3 | 国网三统一模块协议 | MNU↔充电模块 | 125 kbps | PF 驱动 + 定值帧，分组/动态分组双模式，LE |
| 4 | 英飞源充电模块 V107 | 监控↔整流模块 | 125 kbps | CommandNumber 驱动，定点/浮点混用，BE |

核心目标：将四套静态协议文档转化为统一操作界面的可交互工具，覆盖从"查阅报文定义"到"构造 CAN 帧"再到"批量解析抓包数据"的完整工作流。

**适用场景：**

- **研发调试**：根据物理参数构造指定协议的 CAN 帧，验证模块/充电机的报文解析逻辑
- **现场排查**：将抓包 Hex 数据即时翻译为物理量，快速定位异常
- **兼容测试**：批量解析不同厂商模块的 Excel 抓包日志，比对协议实现与标准的偏差
- **跨协议对比**：同一参数（如输出电压）在四套协议中的编码方式并排比较
- **协议学习**：交互式浏览各协议报文定义，理解 CAN ID 布局和字段编码差异

---

## 二、多协议架构总览

### 2.1 核心思想：协议无关引擎 + 协议定义文件

四套协议的差异集中在三个维度：

| 维度 | 27930 | 安世博 | 三统一 | 英飞源 |
|------|-------|--------|--------|--------|
| CAN ID 布局 | P(3)+PF(8)+PS(8)+SA(8) | Protocol(4)+MonAddr(4)+ModAddr(7)+... | 标准扩展帧（PF驱动） | ErrCode(3)+DevNo(4)+CmdNo(6)+Dst(8)+Src(8) |
| 报文识别方式 | PGN / PF | Byte0 低 4 位 MessageType + Byte1 CommandType | PF | CAN ID bit21-16 CommandNumber |
| 数据字节序 | Little-Endian | Big-Endian（数据域） | Little-Endian | Big-Endian（MSB 在前） |
| 数据格式 | 分辨率+偏移量 | 4 字节整数，单位各异 | 分辨率，定值帧独立 | 定点整数 / IEEE 754 浮点数 |
| 通信模型 | 周期性报文 + 超时 | 请求/应答（Set/Read） | 周期性遥信 + 遥控命令 + 心跳 | 请求/应答（读/设置） |

**策略**：编解码引擎保持协议无关，差异全部收敛到 JSON 协议定义文件中。引擎读取协议定义文件中的 `can_id_schema`、`encoding_rules` 和 `message_matcher` 三个配置段，动态适配当前协议。

### 2.2 功能四象限（协议无关）

```
           选择协议
               │
    ┌──────────┴──────────┐
    │   protocol_xxx.json │
    └──────────┬──────────┘
               │
   ┌───────────┼───────────┐
   ▼           ▼           ▼
┌──────┐  ┌───────┐  ┌────────┐
│Query │  │Encode │  │Decode  │
│查询  │  │编码   │  │解码    │
│      │  │       │  │        │
│报文  │  │参数→帧│  │帧→参数 │
│定义  │  │       │  │        │
└──────┘  └───┬───┘  └───┬────┘
              │           │
              └─────┬─────┘
                    ▼
              ┌──────────┐
              │  Parse   │
              │  批量解析 │
              │ Excel导入 │
              │ 结果导出  │
              └──────────┘
```

四个功能在任意协议上行为一致，切换协议时 UI 布局不变，只有数据内容变化。

---

## 三、分层架构

采用严格的三层分离，层间通过明确接口通信。与 v1.0 相比，核心变化在**模型层**：从单一 27930 协议模型升级为协议无关的抽象模型。

```
┌─────────────────────────────────────────────────────────┐
│                      UI 层 (ui/)                        │
│  ┌───────────────────────────────────────────────────┐  │
│  │  协议选择器: [GB/T 27930 ▾]  ← 切换协议重载全界面  │  │
│  ├───────────────────────┬───────────────────────────┤  │
│  │     QueryPanel        │      ParserPanel          │  │
│  │  - 报文树/列表(按协议)│  - Excel 加载区           │  │
│  │  - 搜索栏             │  - 原始数据预览表         │  │
│  │  - 报文详情表         │  - 解码结果表             │  │
│  │  - 编码器弹窗         │  - 导出按钮               │  │
│  │  - CAN ID 解析器      │  - 按协议自动匹配报文     │  │
│  └───────────────────────┴───────────────────────────┘  │
│               QTabWidget / QStackedWidget                │
├─────────────────────────────────────────────────────────┤
│                    服务层 (services/)                    │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │ QueryEngine  │ │ ExcelParser  │ │   CanCodec     │  │
│  │ .by_name()   │ │ .load()      │ │ .decode()      │  │
│  │ .by_id() ①  │ │ .extract()   │ │ .encode()      │  │
│  │ .by_can_id() │ │ .batch()     │ │ .make_can_id() │  │
│  │ .search()    │ │ .export()    │ │ .pack()        │  │
│  │ .by_group()  │ │              │ │ .validate()    │  │
│  └──────────────┘ └──────────────┘ └────────────────┘  │
│                        ↑                                │
│              所有服务接受 ProtocolDefinition             │
│              在构造时注入，协议无关                      │
├─────────────────────────────────────────────────────────┤
│                  数据模型层 (models/)                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │            ProtocolDefinition  (协议无关容器)       │  │
│  │  - meta: 协议名称/版本/波特率/字节序                │  │
│  │  - can_id_schema: CAN ID 位域布局定义              │  │
│  │  - addresses: 地址表                               │  │
│  │  - message_matcher: 报文识别策略                    │  │
│  │  - encoding_rules: 编码规则默认值                   │  │
│  │  - messages: List[MessageDef]                      │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │  MessageDef                                 │  │  │
│  │  │  .name, .identifier                        │  │  │
│  │  │  .direction, .cycle_ms, .data_length        │  │  │
│  │  │  .tp                                         │  │  │
│  │  │  .fields: List[FieldDef]                     │  │  │
│  │  │  ┌───────────────────────────────────────┐  │  │  │
│  │  │  │  FieldDef                             │  │  │  │
│  │  │  │  .name, .spn (或 .param_id)           │  │  │  │
│  │  │  │  .byte_start, .length                 │  │  │  │
│  │  │  │  .bit_start, .bit_len                 │  │  │  │
│  │  │  │  .data_type ②                         │  │  │  │
│  │  │  │  .resolution, .offset                 │  │  │  │
│  │  │  │  .unit, .range_min, .range_max         │  │  │  │
│  │  │  │  .enum: Dict[int, str]                │  │  │  │
│  │  │  │  .required: bool                      │  │  │  │
│  │  │  └───────────────────────────────────────┘  │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  data/                                           │   │
│  │  ├── gbt27930_v1.1.json                          │   │
│  │  ├── anshibo_1k040b.json                         │   │
│  │  ├── sg_unified_v107.json                        │   │
│  │  └── infypower_v107.json                         │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘

① by_id() 替代 v1.0 的 by_pgn() — 因为不同协议的报文标识符类型不同
② data_type 为新增字段 — 支持 "int_le", "int_be", "float_ieee754", "bcd", "ascii"
```

### 3.1 各层职责

| 层 | 职责 | 约束 |
|----|------|------|
| 模型层 | 协议元数据结构化表达，JSON 加载与校验，CAN ID 位域解析 | 不依赖任何 GUI 库，不包含业务逻辑 |
| 服务层 | 查询、编码、解码、Excel 读写的核心算法 | 协议无关：构造时注入 `ProtocolDefinition` |
| UI 层 | 窗口、布局、表格渲染、协议切换、用户交互 | 仅调用服务层接口 |

### 3.2 协议切换的数据流

```
用户在 UI 选择协议
    │
    ▼
UI 调用 ProtocolLoader.load("gbt27930_v1.1.json")
    │
    ▼
构建 ProtocolDefinition 对象
    │
    ├──→ 构建 QueryEngine(protocol)
    ├──→ 构建 CanCodec(protocol)
    └──→ 构建 ExcelParser(codec, query)
    │
    ▼
UI 用新的引擎实例刷新全部视图:
  - 报文列表重建
  - 详情表刷新
  - 编码器输入框动态生成
  - 搜索索引重建
```

---

## 四、技术选型

### 4.1 GUI 框架：PySide6（Qt for Python）

| 考量维度 | PySide6 表现 |
|---------|-------------|
| 表格渲染 | QTableView + 自定义 Model，支持大数据量、排序、筛选、条件格式化 |
| 多视图切换 | QTabWidget / QStackedWidget 原生支持面板切换 |
| 布局灵活性 | QSplitter 实现左右分栏拖拽，嵌套构建复杂仪表盘布局 |
| 动态表单 | 编码器输入框可根据不同协议的字段定义动态生成 |
| Windows 原生外观 | Qt Windows 样式引擎，与系统主题一致 |
| 可视化设计 | Qt Designer 拖拽构建界面原型 |
| 许可证 | LGPLv3 |

### 4.2 技术栈总览

| 层 | 技术 | 用途 |
|----|------|------|
| GUI | PySide6 ≥ 6.5 | 桌面窗口、表格、控件 |
| Excel 读取 | pandas + openpyxl | 加载抓包 Excel，DataFrame 操作 |
| Excel 写出 | openpyxl / xlsxwriter | 导出解码结果 |
| 协议存储 | JSON（每协议一个文件） | 协议定义的单一数据源 |
| 数据模型 | Python dataclass | 类型安全的协议对象 |
| 数值计算 | Python `struct` | LE/BE 字节打包/解包 |
| 浮点数 | Python `struct` (IEEE 754) | 英飞源协议的浮点编码 |
| 测试 | pytest | 服务层单元测试、编解码闭环验证 |
| 打包分发 | PyInstaller | 生成独立 exe |

---

## 五、核心抽象设计 — 协议差异的收敛

### 5.1 CAN ID Schema 抽象

不同协议的 CAN ID 位域布局完全不同。通过 `can_id_schema` 定义，引擎动态解析和构造。

**GB/T 27930：**

```json
{
  "can_id_schema": {
    "total_bits": 29,
    "fields": [
      {"name": "priority",    "bit_start": 26, "bit_len": 3, "description": "优先权"},
      {"name": "edp",         "bit_start": 25, "bit_len": 1, "fixed_value": 0},
      {"name": "dp",          "bit_start": 24, "bit_len": 1, "fixed_value": 0},
      {"name": "pf",          "bit_start": 16, "bit_len": 8, "description": "PDU格式"},
      {"name": "ps",          "bit_start": 8,  "bit_len": 8, "description": "目标地址"},
      {"name": "sa",          "bit_start": 0,  "bit_len": 8, "description": "源地址"}
    ],
    "message_identifier": "pf",
    "identifier_field": "pf"
  }
}
```

**英飞源 V107：**

```json
{
  "can_id_schema": {
    "total_bits": 29,
    "fields": [
      {"name": "error_code",     "bit_start": 26, "bit_len": 3, "description": "错误码"},
      {"name": "device_number",  "bit_start": 22, "bit_len": 4, "description": "设备号"},
      {"name": "command_number", "bit_start": 16, "bit_len": 6, "description": "命令号"},
      {"name": "dest_addr",      "bit_start": 8,  "bit_len": 8, "description": "目的地址"},
      {"name": "source_addr",    "bit_start": 0,  "bit_len": 8, "description": "源地址"}
    ],
    "message_identifier": "command_number",
    "identifier_field": "command_number"
  }
}
```

**安世博：**

```json
{
  "can_id_schema": {
    "total_bits": 29,
    "fields": [
      {"name": "protocol",          "bit_start": 25, "bit_len": 4, "fixed_value": 1},
      {"name": "monitor_address",   "bit_start": 21, "bit_len": 4, "description": "监控地址"},
      {"name": "module_address",    "bit_start": 14, "bit_len": 7, "description": "模块地址"},
      {"name": "production_day",    "bit_start": 9,  "bit_len": 5, "description": "生产日期"},
      {"name": "serial_number_low", "bit_start": 0,  "bit_len": 9, "description": "序列号低位"}
    ],
    "message_identifier": "data_field",
    "identifier_field": "command_type",
    "identifier_byte": 1
  }
}
```

> 安世博协议的报文类型不由 CAN ID 字段直接确定，而是由数据域 Byte1（CommandType）和 Byte0 低 4 位（MessageType）联合确定。`message_identifier: "data_field"` 告知引擎去数据域中查找。

**What this enables:** `CanCodec.make_can_id()` 不再硬编码 27930 的位移计算，而是读取 `can_id_schema.fields`，遍历每个字段，从 `MessageDef` 的对应属性中取值，按 `bit_start` 位移拼接。

### 5.2 报文标识符抽象

不同协议用不同方式定位一条报文。`MessageDef` 的 `identifier` 字段根据 `can_id_schema.message_identifier` 取值：

```python
# 27930: 通过 PF 识别
{"identifier": {"pf": 16}}

# 英飞源: 通过 command_number + device_number 联合识别
{"identifier": {"command_number": 1, "device_number": 10}}

# 安世博: 通过 command_type + message_type 联合识别
{"identifier": {"command_type": 0, "message_type": "ReadData"}}
```

`QueryEngine.by_id()` 接受一个 identifier dict，协议无关地查找：

```python
msg = query.by_id({"pf": 16})                    # 27930: 找 PF=16 的报文 → BCL
msg = query.by_id({"command_number": 0x01})      # 英飞源: 找命令号 0x01
msg = query.by_id({"command_type": 0, "message_type": "SetData"})  # 安世博
```

### 5.3 数据格式抽象

FieldDef 新增 `data_type` 字段，支持四种协议的全部格式：

| data_type | 说明 | 字节序 | 使用协议 |
|-----------|------|--------|---------|
| `int_le` | 整数，Little-Endian | LE | 27930, 三统一 |
| `int_be` | 整数，Big-Endian (MSB在前) | BE | 英飞源, 安世博 |
| `float_ieee754` | IEEE 754 单精度浮点 | MSB阶码在前 | 英飞源 |
| `bits` | 位域（bit 级定义） | N/A | 27930 BSM, 英飞源状态表 |
| `bcd` | 压缩 BCD | N/A | 27930 CTS |
| `ascii` | ASCII 字符串 | N/A | 27930 BRM (厂商名、EVIN) |

编码/解码时引擎根据 `data_type` 走不同分支：

```python
def _pack_field(self, field: FieldDef, value: Any) -> bytes:
    if field.data_type == "int_le":
        raw = int((value - field.offset) / field.resolution)
        return struct.pack("<" + self._fmt(field.length), raw)
    elif field.data_type == "int_be":
        raw = int(value / field.resolution)  # 英飞源/安世博通常无偏移
        return struct.pack(">" + self._fmt(field.length), raw)
    elif field.data_type == "float_ieee754":
        return struct.pack(">f", value)
    elif field.data_type == "bits":
        return self._pack_bits(field, value)
    ...
```

### 5.4 变长数据域处理

四种协议中存在不同形式的变长或非标准数据布局：

| 协议 | 变长场景 | 处理方式 |
|------|---------|---------|
| 27930 | BMV 不定长（N×2字节）、BRM 49字节 TP | `data_length: null` + `tp: true`，从实际字节数反推单体数 |
| 安世博 | AllSetData 时 Byte1 含义变化 | `layout_override` 字段，指定条件触发的替代布局 |
| 英飞源 | 不同命令数据域完全不同 | 每命令独立定义，无通用模板 |
| 三统一 | 定值帧 48 项参数按序号索引 | `param_index` 字段独立映射，非连续字节布局 |

**设计策略**：在 `MessageDef` 中支持可选的 `layout_overrides` 列表，每个 override 包含触发条件和替代字段列表。引擎在解析时先检测条件，匹配则切换布局。

---

## 六、JSON 协议定义文件完整结构

### 6.1 顶层结构

```json
{
  "meta": {
    "protocol_name": "GB/T 27930-2023 A类系统",
    "protocol_id": "gbt27930_v1.1",
    "version": "V1.1",
    "standard": "GB/T 27930-2023",
    "baud_rate": 250000,
    "frame_format": "CAN_2.0B_EXTENDED"
  },
  "can_id_schema": { /* 见 5.1 */ },
  "addresses": {
    "SECC": {"value": 86, "hex": "0x56", "name": "充电机"},
    "EVCC": {"value": 244, "hex": "0xF4", "name": "车辆"}
  },
  "encoding_rules": {
    "default_byte_order": "little_endian",
    "undefined_bit_fill": 1
  },
  "message_matcher": {
    "type": "pf_based",
    "match_field": "pf"
  },
  "message_groups": [
    {
      "name": "充电握手阶段",
      "messages": ["CHM", "BHM", "CRM", "BRM"]
    }
  ],
  "messages": [ /* 见 6.2 */ ]
}
```

### 6.2 各协议报文定义示例

#### 27930 — BCL

```json
{
  "name": "电池充电需求",
  "abbr": "BCL",
  "identifier": {"pf": 16},
  "can_id_template": {
    "priority": 6,
    "pf": 16,
    "ps": "{target_addr}",
    "sa": "{source_addr}"
  },
  "direction": "EVCC_to_SECC",
  "cycle_ms": 50,
  "data_length": 5,
  "tp": false,
  "fields": [
    {
      "name": "车辆接口充电电压需求", "spn": 3072,
      "byte_start": 1, "length": 2,
      "data_type": "int_le", "resolution": 0.1, "offset": 0.0,
      "unit": "V", "range": [0, 6553.5], "required": true
    },
    {
      "name": "车辆接口充电电流需求", "spn": 3073,
      "byte_start": 3, "length": 2,
      "data_type": "int_le", "resolution": 0.1, "offset": -400.0,
      "unit": "A", "range": [-400, 2153.5], "required": true
    },
    {
      "name": "充电模式", "spn": 3074,
      "byte_start": 5, "length": 1,
      "data_type": "int_le",
      "enum": {"1": "恒压充电", "2": "恒流充电"}, "required": true
    }
  ]
}
```

#### 安世博 — 读取模块输出电压 (CommandType=0)

```json
{
  "name": "读取模块输出电压",
  "abbr": "CMD_00",
  "identifier": {"command_type": 0},
  "can_id_template": {
    "protocol": 1,
    "monitor_address": 1,
    "module_address": "{module_addr}"
  },
  "direction": "MON_to_MODULE",
  "request_response": "request",
  "data_template": {
    "byte0": {"group_address": 1, "message_type": "ReadData"},
    "byte1": 0,
    "bytes_2_3": 0,
    "bytes_4_7": 0
  },
  "response_message": "CMD_00_RESP",
  "fields": [
    {
      "name": "模块输出电压", "param_id": 0,
      "byte_start": 4, "length": 4,
      "data_type": "int_be",
      "unit": "mV", "resolution": 1, "offset": 0,
      "range": [0, 4294967295], "required": true
    }
  ]
}
```

> 安世博的请求帧和应答帧是两条不同的报文（MessageType 不同），通过 `request_response` 和 `response_message` 字段建立关联。

#### 英飞源 — 命令 0x01 读系统电压电流（浮点）

```json
{
  "name": "读取系统电压电流（浮点）",
  "abbr": "CMD_01",
  "identifier": {"command_number": 1, "device_number": 10},
  "can_id_template": {
    "error_code": 0,
    "device_number": 10,
    "command_number": 1,
    "dest_addr": "{target_addr}",
    "source_addr": "{source_addr}"
  },
  "direction": "MON_to_MODULE",
  "data_length": 8,
  "fields": [
    {
      "name": "系统电压", "param_id": 0,
      "byte_start": 0, "length": 4,
      "data_type": "float_ieee754",
      "unit": "V", "required": true
    },
    {
      "name": "系统总电流", "param_id": 1,
      "byte_start": 4, "length": 4,
      "data_type": "float_ieee754",
      "unit": "A", "required": true
    }
  ]
}
```

#### 三统一 — 遥控命令帧 (PF=0x01)

```json
{
  "name": "遥控命令（固定分组）",
  "abbr": "RC_CMD",
  "identifier": {"pf": 1},
  "can_id_template": {
    "priority": 6,
    "pf": 1,
    "ps": "{target_addr}",
    "sa": "{source_addr}"
  },
  "direction": "MNU_to_MODULE",
  "data_length": 8,
  "fields": [
    {
      "name": "控制字", "param_id": 0,
      "byte_start": 0, "length": 1, "data_type": "bits",
      "bit_fields": [
        {"name": "操作指令", "bit_start": 0, "bit_len": 4, "enum": {"1": "快速开机", "2": "停止充电", "3": "软启动", "4": "显示地址", "5": "参数修改"}},
        {"name": "输出电压范围", "bit_start": 4, "bit_len": 1, "enum": {"0": "低压段", "1": "高压段"}},
        {"name": "功分接触器", "bit_start": 5, "bit_len": 1, "enum": {"0": "分断", "1": "闭合"}},
        {"name": "主接触器", "bit_start": 6, "bit_len": 1, "enum": {"0": "分断", "1": "闭合"}}
      ],
      "required": true
    },
    {
      "name": "分组编码", "param_id": 1,
      "byte_start": 1, "length": 1, "data_type": "int_le",
      "required": false
    },
    {
      "name": "给定电压", "param_id": 2,
      "byte_start": 2, "length": 2, "data_type": "int_le",
      "resolution": 0.1, "unit": "V", "range": [0, 1000], "required": true
    },
    {
      "name": "给定电流", "param_id": 3,
      "byte_start": 4, "length": 2, "data_type": "int_le",
      "resolution": 0.01, "unit": "A", "range": [0, 600], "required": true
    },
    {
      "name": "电池电压", "param_id": 4,
      "byte_start": 6, "length": 2, "data_type": "int_le",
      "resolution": 0.1, "unit": "V", "range": [0, 1000], "required": true
    }
  ]
}
```

---

## 七、核心服务设计（协议无关）

### 7.1 QueryEngine

```python
class QueryEngine:
    def __init__(self, protocol: ProtocolDefinition): ...

    # 通用查询
    def by_name(self, name: str) -> Optional[MessageDef]: ...
    def by_abbr(self, abbr: str) -> Optional[MessageDef]: ...
    def by_id(self, identifier: dict) -> Optional[MessageDef]:
        """
        identifier 格式取决于协议的 message_matcher.type:
          pf_based → {"pf": 16}
          command_number → {"command_number": 1, "device_number": 10}
          data_field → {"command_type": 0, "message_type": "ReadData"}
        """
    def by_can_id(self, can_id: int) -> Optional[MessageDef]:
        """
        从 CAN ID 中根据 can_id_schema 提取标识符字段，再调用 by_id()
        """
    def by_group(self, group_name: str) -> List[MessageDef]: ...
    def search(self, keyword: str) -> List[MessageDef]: ...
    def all_messages(self) -> List[MessageDef]: ...
    def all_groups(self) -> List[str]: ...
    def get_protocol_info(self) -> dict: ...
```

### 7.2 CanCodec

```python
class CanCodec:
    def __init__(self, protocol: ProtocolDefinition): ...

    def decode(self, identifier: dict, data: bytes) -> Dict[str, Any]:
        """通用解码：identifier 定位报文 → 按字段布局解包"""

    def encode(self, identifier: dict, **params) -> dict:
        """通用编码：返回 {"can_id": int, "can_id_hex": str, "data": bytes, "data_hex": str}"""

    def make_can_id(self, identifier: dict, **addr_overrides) -> int:
        """从 can_id_schema 动态拼接 CAN ID"""

    def parse_can_id(self, can_id: int) -> dict:
        """从 CAN ID 提取各字段 → {"pf": 16, "priority": 6, "sa": 244, ...}"""

    def identify_message(self, can_id: int, data: Optional[bytes] = None) -> Optional[dict]:
        """
        从完整的 CAN 帧识别报文类型。
        对于 message_matcher.type == "data_field" 的协议，需要 data 参数。
        """

    # 内部方法（data_type 多态）
    def _pack_field(self, field: FieldDef, value: Any) -> bytes: ...
    def _unpack_field(self, field: FieldDef, data: bytes) -> Any: ...
    def _pack_int_le(self, value, field): ...
    def _pack_int_be(self, value, field): ...
    def _pack_float_ieee754(self, value, field): ...
    def _pack_bits(self, value, field): ...
    def _pack_bcd(self, value, field): ...
```

### 7.3 ExcelParser

```python
class ExcelParser:
    def __init__(self, codec: CanCodec, query: QueryEngine): ...

    def load(self, filepath: str) -> pd.DataFrame: ...
    def parse(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        逐行: CAN ID → identify_message() → decode() → 展开结果列
        无法匹配的行标记为 'UNKNOWN'，解码失败的行标记错误原因
        """
    def export(self, df: pd.DataFrame, filepath: str) -> None: ...
```

**Excel 解析多协议适配要点：**

- 解析前要求用户确认当前协议（与 Excel 抓包来源一致）
- 同一 Excel 中不同 CAN ID 可能对应不同报文，引擎自动匹配
- 安世博/英飞源等请求/应答型协议，可选项：将请求帧和应答帧配对显示

---

## 八、UI 设计 — 协议切换机制

### 8.1 协议选择器

窗口顶部（工具栏或菜单栏）增加协议下拉选择器：

```
┌──────────────────────────────────────────────────┐
│  Protocol Converter                     [_][□][×]│
├──────────────────────────────────────────────────┤
│  协议: [GB/T 27930-2023 ▾]  波特率: 250 kbps    │
│        ├ GB/T 27930-2023 A类系统                 │
│        ├ 安世博 UAA-1K040B-E                     │
│        ├ 国网三统一模块 V107                      │
│        └ 英飞源充电模块 V107                      │
├──────────────────────────────────────────────────┤
│  [查询]  [编码/解码]  [Excel解析]                 │
├──────────────────────────────────────────────────┤
│  ...                                             │
```

切换协议后：
- 报文列表重建（27930 按阶段分组 → 安世博按 CommandType 列表）
- 详情表列头可能变化（27930 有 SPN 列，安世博无）
- 编码器输入框动态生成
- 状态栏更新协议名称、报文数量

### 8.2 查询面板（按协议自适应）

**27930 / 三统一（PF 驱动型）：**

```
┌──── 充电握手阶段 ────┐
│  CHM  充电机握手      │
│  BHM  车辆握手        │
│  CRM  充电机辨识      │
│  BRM  BMS和车辆辨识   │
├──── 参数配置阶段 ────┤
│  BCP  车辆充电参数    │
│  CTS  时间同步        │
│  ...                  │
└──────────────────────┘
```

**安世博 / 英飞源（命令列表型）：**

```
┌── 读取命令 ──────────┐
│ CMD_00  输出电压      │
│ CMD_01  输出电流      │
│ CMD_08  状态标志      │
├── 设置命令 ──────────┤
│ CMD_02  电压设定      │
│ CMD_03  限流设定      │
│ CMD_04  开关机        │
└──────────────────────┘
```

列表分组依据来自 JSON 的 `message_groups`，无分组时平铺显示。

### 8.3 CAN ID 解析器（协议自适应）

在查询面板中展示选中报文的 CAN ID 逐位分解：

```
┌─ CAN ID 解析 ──────────────────────────────────┐
│  CAN ID: 0x181056F4                            │
│                                                │
│  ┌──────┬─────┬─────┬──────────┬──────┬──────┐ │
│  │  P   │ EDP │ DP  │    PF    │  PS  │  SA  │ │
│  │ 110  │  0  │  0  │ 00010000 │0x56  │0xF4  │ │
│  │  6   │  0  │  0  │   16     │ SECC │ EVCC │ │
│  └──────┴─────┴─────┴──────────┴──────┴──────┘ │
│                                                │
│  优先权: 6 (普通数据报文)                       │
│  PF: 0x10 → BCL (电池充电需求)                  │
│  方向: EVCC(车辆) → SECC(充电机)                │
└────────────────────────────────────────────────┘
```

切换到英飞源时，同一个 29-bit ID 按英飞源的位域布局重新渲染：

```
┌─ CAN ID 解析 ──────────────────────────────────────┐
│  CAN ID: 0x028100F0                                │
│                                                    │
│  ┌───────┬──────┬─────────────┬──────────┬───────┐ │
│  │ErrCode│DevNo │CommandNumber│ DestAddr │SrcAddr│ │
│  │  000  │ 1010 │   000001    │  0x00    │ 0xF0  │ │
│  │   0   │ 0x0A │    0x01    │ 模块#0   │ 监控  │ │
│  └───────┴──────┴─────────────┴──────────┴───────┘ │
│                                                    │
│  设备号: 0x0A (监控→模块点对点)                     │
│  命令号: 0x01 → 读取系统电压电流(浮点)              │
│  方向: 监控(0xF0) → 模块#0(0x00)                   │
└────────────────────────────────────────────────────┘
```

CAN ID 解析器读取 `can_id_schema` 动态渲染，与协议无关。

---

## 九、开发路线图

### 里程碑 1：协议无关数据模型 + 四份 JSON 协议文件

**产物：**
- `models/protocol.py` — 协议无关的 dataclass 定义（含 `CanIdSchema`、`MessageMatcher`、`FieldDef.data_type`）
- `models/loader.py` — JSON 加载与 schema 校验
- `data/gbt27930_v1.1.json` — 27930 全部 22 条报文
- `data/anshibo_1k040b.json` — 安世博全部 28 条命令
- `data/sg_unified_v107.json` — 三统一全部 13 条报文帧 + 定值参数
- `data/infypower_v107.json` — 英飞源全部 16 条命令

---

### 里程碑 2：协议无关命令行编解码器

**产物：**
- `services/can_codec.py` — 支持全部 data_type 的编解码
- `services/query_engine.py` — 支持三种 message_matcher 类型
- `tests/test_codec_27930.py` — 27930 编解码闭环
- `tests/test_codec_anshibo.py` — 安世博编解码
- `tests/test_codec_infypower.py` — 英飞源编解码（含浮点）
- `tests/test_codec_sg_unified.py` — 三统一编解码（含位域控制字）

---

### 里程碑 3：GUI — 协议选择 + 查询面板

**产物：**
- `ui/main_window.py` — 主窗口 + 协议切换
- `ui/query_panel.py` — 自适应报文列表 + 详情表 + CAN ID 解析器
- `ui/encode_dialog.py` — 动态表单编码器

---

### 里程碑 4：GUI — Excel 批量解析 + 导出

**产物：**
- `services/excel_parser.py` — 协议无关批量解析
- `ui/parser_panel.py` — 加载/预览/解析/导出全流程

---

### 里程碑 5（远期）

- **请求/应答配对模式**：对安世博/英飞源等请求/应答型协议，自动配对显示
- **实时 CAN 接入**：PCAN / SocketCAN 硬件接口，实时解码
- **协议差异对比**：同一参数（如输出电压设定）在四套协议中的编码并排比较
- **报文序列回放**：按时间轴可视化多协议通信流程
- **用户自定义协议**：GUI 引导式创建新协议 JSON

---

## 十、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 协议存储 | 每协议一个 JSON 文件 | 独立维护，互不干扰，单协议修改不影响其他协议 |
| 协议切换机制 | 构造新引擎实例 | 清晰无状态，避免全局可变状态引发的 bug |
| CAN ID 抽象 | `can_id_schema` 动态描述位域 | 避免硬编码，四种布局一套代码处理 |
| 报文识别 | `message_matcher.type` 策略模式 | 支持 PF / CommandNumber / DataField 三种识别方式 |
| 数据格式 | FieldDef.data_type 多态 | 整数 LE/BE、浮点 IEEE 754、位域、BCD、ASCII 统一入口 |
| 变长/特殊布局 | `layout_overrides` 可选字段 | 安世博 AllSetData、三统一定值帧等特殊情况优雅处理 |
| 字节序 | 协议级默认 + 字段级可覆盖 | 大部分协议一致（如英飞源全是 BE），少数例外可单字段指定 |
| 数值类型 | struct + IEEE 754 | 标准库覆盖所有需求，零额外依赖 |

---

## 十一、目录结构

```
protocol_converter/
├── readme/
│   └── protocol_converter-v1.1.md
├── data/
│   ├── gbt27930_v1.1.json             # GB/T 27930-2023 协议定义
│   ├── anshibo_1k040b.json             # 安世博 UAA-1K040B-E 协议定义
│   ├── sg_unified_v107.json            # 国网三统一模块协议定义
│   └── infypower_v107.json             # 英飞源充电模块协议定义
├── models/
│   ├── __init__.py
│   ├── protocol.py                     # 协议无关数据模型
│   │   ├── CanIdSchema / CanIdField    # CAN ID 位域布局
│   │   ├── MessageDef / FieldDef       # 报文/字段定义
│   │   ├── ProtocolDefinition          # 协议顶层容器
│   │   └── EncodingRules               # 编码规则
│   └── loader.py                       # JSON 加载与 schema 校验
├── services/
│   ├── __init__.py
│   ├── query_engine.py                 # 协议无关查询引擎
│   ├── can_codec.py                    # 协议无关编解码器
│   │   ├── CanIdBuilder                # CAN ID 构造/解析
│   │   ├── FieldPacker                 # 字段打包 (int_le/be, float, bits, bcd)
│   │   └── FieldUnpacker               # 字段解包
│   └── excel_parser.py                 # Excel 批量解析
├── ui/
│   ├── __init__.py
│   ├── main_window.py                  # 主窗口 + 协议选择器
│   ├── query_panel.py                  # 查询面板（协议自适应）
│   ├── encode_dialog.py                # 编码器弹窗（动态表单）
│   ├── decode_panel.py                 # 单帧解码面板
│   ├── can_id_viewer.py                # CAN ID 位域可视化组件
│   └── parser_panel.py                 # Excel 解析面板
├── tests/
│   ├── __init__.py
│   ├── test_codec_27930.py
│   ├── test_codec_anshibo.py
│   ├── test_codec_infypower.py
│   ├── test_codec_sg_unified.py
│   ├── test_query.py
│   └── test_parser.py
├── main.py
├── requirements.txt
└── README.md
```
