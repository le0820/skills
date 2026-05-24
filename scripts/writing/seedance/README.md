# Creative Pipeline - InkOS + Seedance

从灵感到小说/短剧的自动化创作系统。

## 快速开始

### 1. 配置环境

```bash
cp .env.example .env
# 编辑 .env，填入你的API Key
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行示例

```bash
# 从灵感到小说
python main.py novel

# 从灵感到短剧
python main.py drama

# 混合模式（小说+短剧）
python main.py hybrid
```

## 项目结构

```
seedance/
├── orchestrator/          # 编排层
│   ├── schema.py          # 统一数据格式
│   ├── core.py            # 核心编排器
│   └── clients/
│       └── inkos_client.py
├── agents/                # Seedance Agent系统
│   ├── director.py        # 总导演
│   ├── screenplay.py      # 剧本创作
│   ├── character_design.py # 角色设计
│   ├── action_design.py   # 动作设计
│   ├── prompt_engineer.py # 提示词工程
│   └── llm_client.py      # LLM客户端
├── extractors/            # 内容提取器
│   └── novel_extractor.py
├── converters/            # 格式转换器（预留）
├── main.py                # 主入口
├── .env.example           # 环境变量模板
└── requirements.txt       # Python依赖
```

## 使用方式

### Python API

```python
from orchestrator import CreativeOrchestrator

orchestrator = CreativeOrchestrator()

result = await orchestrator.run_pipeline({
    'title': '我的故事',
    'premise': '一个程序员意外获得超能力...',
    'mode': 'novel',  # 或 'drama', 'hybrid'
    'output': {
        'chapters': 10,
        'words_per_chapter': 3000
    }
})
```

### 运行模式

| 模式 | 说明 | 输出 |
|------|------|------|
| novel | 只生成小说 | 小说文件 |
| drama | 只生成短剧 | 剧本 + 视频提示词 |
| hybrid | 小说+短剧 | 小说 + 剧本 + 视频提示词 |

## 配置说明

### LLM配置（inkos & scripts 共用）

```bash
LLM_PROVIDER=openai
LLM_API_KEY=sk-xxx
LLM_MODEL=gpt-4o
```

### 重试配置

```bash
MAX_RETRIES=2
RETRY_DELAY_SECONDS=5
LLM_TIMEOUT_SECONDS=60
```

## 文档

- [PIPELINE_INTEGRATION.md](PIPELINE_INTEGRATION.md) - 管线串联方案
- [LOGIC_VALIDATION.md](LOGIC_VALIDATION.md) - 逻辑验证说明
