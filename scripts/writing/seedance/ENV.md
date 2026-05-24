# seedance/inkos 环境说明

## 项目结构

- `inkos/` — Node.js 项目，自动化小说写作 CLI Agent
- `novel_gen/` — 小说生成相关素材
- Python 虚拟环境用于项目管理工具

## Node.js 环境 (inkos)

依赖已通过 pnpm 安装，`node_modules/` 已就绪。

### 运行命令

```bash
# 在 inkos 目录下执行
cd scripts/writing/seedance/inkos
npx inkos <command>

# 或全局安装后直接调用
npm i -g @actalk/inkos
inkos <command>
```

### 常用命令

```bash
inkos init my-project                    # 初始化项目
inkos book create --title "书名" --genre xuanhuan  # 创建书籍
inkos write next <book-id>               # 写下一章
inkos status                             # 查看状态
inkos doctor                             # 诊断配置
```

### 配置 LLM

```bash
inkos config set-global \
  --provider openai \
  --base-url https://api.openai.com/v1 \
  --api-key sk-xxx \
  --model gpt-4o
```

## Python 环境

路径: `.venv/` (Python 3.11)

```bash
# 激活
source scripts/writing/seedance/.venv/bin/activate

# 直接调用
scripts/writing/seedance/.venv/bin/python main.py
```

## 安装新依赖

```bash
# Node.js
cd scripts/writing/seedance/inkos && pnpm add <package>

# Python
scripts/writing/seedance/.venv/bin/pip install <package>
```
