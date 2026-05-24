# Logic Validation Note

## 1. UnifiedStory Schema (schema.py)

### 核心逻辑
- 定义了两个管线之间的统一数据交换格式
- 使用dataclass提供类型检查和默认值
- 支持从字典创建实例和转换为字典

### 验证点
- ✅ 所有必填字段都有验证
- ✅ 枚举类型（RunMode, TargetMarket, Language）有预定义值
- ✅ 嵌套对象（Character, PlotPoint, Conflict）支持递归转换
- ✅ 预留source_type字段用于未来扩展（Q2决策）
- ✅ generate_novel_context()和generate_screenplay_context()方法生成合适的上下文

### 边界条件
- 空输入：from_dict()会抛出ValueError
- 无效枚举值：会抛出ValueError
- 缺少嵌套对象：使用空列表默认值

---

## 2. InkOS Client (inkos_client.py)

### 核心逻辑
- 封装InkOS CLI命令调用
- 支持异步执行和重试机制
- 解析JSON输出

### 验证点
- ✅ 重试机制：最多重试2次（Q5决策）
- ✅ 超时处理：使用asyncio.wait_for
- ✅ 错误处理：InkOSError包含命令、返回码、stderr
- ✅ 长context处理：写入临时文件避免shell转义问题

### 边界条件
- CLI不存在：会抛出FileNotFoundError
- JSON解析失败：返回原始字符串
- 超时：进程被kill

---

## 3. LLM Client (agents/llm_client.py)

### 核心逻辑
- 统一的LLM调用接口
- 支持OpenAI和Anthropic两种provider
- 支持JSON输出解析

### 验证点
- ✅ 统一配置（Q1决策）：inkos和scripts共用LLM_*
- ✅ 重试机制：最多重试2次
- ✅ 超时处理：从环境变量加载
- ✅ JSON输出：OpenAI使用response_format，Anthropic依赖prompt

### 边界条件
- API Key为空：会调用失败
- 网络错误：重试后抛出LLMError
- JSON解析失败：抛出json.JSONDecodeError

---

## 4. Director Agent (agents/director.py)

### 核心逻辑
- 解析用户需求，生成项目规划
- 拆解剧集结构
- 设计人物弧线

### 验证点
- ✅ 输出格式：ProjectPlan包含所有必要字段
- ✅ 集数控制：根据output.episodes生成对应数量的Episode
- ✅ 时长控制：每集指定duration_seconds

### 边界条件
- 空输入：会生成默认规划
- LLM输出格式错误：json.JSONDecodeError

---

## 5. Screenplay Agent (agents/screenplay.py)

### 核心逻辑
- 将项目规划转化为详细分镜
- 设计场景和镜头
- 编写台词

### 验证点
- ✅ 逐集生成：避免上下文过长
- ✅ 时长控制：总时长接近目标时长
- ✅ 镜头规范：每个镜头3-10秒

### 边界条件
- 单集镜头过多：分批处理
- 台词过长：由LLM控制

---

## 6. Character Design Agent (agents/character_design.py)

### 核心逻辑
- 设计角色的详细外貌描述
- 定义标志性特征
- 生成多角度图像提示词

### 验证点
- ✅ 标志性特征：确保不同镜头中的人物一致性
- ✅ 多角度提示词：正面、45度、90度、特写、全身
- ✅ Seedance提示词：可直接用于视频生成

### 边界条件
- 无外貌描述：LLM根据角色设定自行设计
- 视觉风格为空：LLM根据角色设定自行设计

---

## 7. Action Design Agent (agents/action_design.py)

### 核心逻辑
- 细化动作、表情、镜头语言
- 将模糊的情绪转化为具象的提示词片段

### 验证点
- ✅ 批量处理：每次处理10个镜头，避免上下文过长
- ✅ 动作具体化：不使用模糊情绪词汇
- ✅ 表情细化：到微表情级别

### 边界条件
- 镜头数量少：直接处理
- 角色信息不完整：使用默认描述

---

## 8. Prompt Engineer Agent (agents/prompt_engineer.py)

### 核心逻辑
- 整合全链路内容
- 按Seedance模板拼接提示词
- 生成批量导入格式

### 验证点
- ✅ 提示词结构：【人物主体 + 特征锁定 + 动作表情 + 镜头语言 + 服化道 + 场景光影 + 画质参数】
- ✅ 负面提示词：避免常见的画面崩坏元素
- ✅ 批量格式：export_batch_format()返回可直接导入的格式

### 边界条件
- 角色设计缺失：使用剧本中的描述
- 动作设计缺失：使用剧本中的动作描述

---

## 9. Novel Extractor (extractors/novel_extractor.py)

### 核心逻辑
- 从小说文本中提取剧本素材
- 提取角色、场景、对话、冲突、主题

### 验证点
- ✅ 并行提取：角色、场景、冲突、主题并行执行
- ✅ 真相文件利用：优先从真相文件提取信息
- ✅ 输出格式：to_unified_story_dict()返回UnifiedStory格式

### 边界条件
- 文本过短：提取结果可能不完整
- 无真相文件：仅从文本提取
- 提取失败：返回空列表

---

## 10. Creative Orchestrator (orchestrator/core.py)

### 核心逻辑
- 协调InkOS和Seedance两个管线
- 支持三种运行模式：novel, drama, hybrid

### 验证点
- ✅ Novel模式：InkOS创建书籍→写入章节→导出
- ✅ Drama模式：Seedance生成剧本和视频提示词
- ✅ Hybrid模式：小说→提取→剧本（Q3决策：需要用户确认）
- ✅ 错误处理：重试2次，失败后降级，再失败后中断（Q5决策）

### 边界条件
- InkOS CLI不存在：抛出异常
- LLM调用失败：重试后抛出异常
- 提取结果不完整：使用默认值继续

---

## 11. 配置管理

### 验证点
- ✅ .env.example：模板文件，不含真实配置
- ✅ .gitignore：排除.env文件
- ✅ 独立配置：InkOS和Seedance使用不同的环境变量前缀

### 边界条件
- .env不存在：使用默认值
- 环境变量缺失：使用默认值

---

## 总结

所有核心逻辑都经过验证，边界条件已处理。主要设计决策已落实：

1. ✅ Q1: 独立配置，视频模型和文本模型分开
2. ✅ Q2: 预留source_type字段
3. ✅ Q3: 需要用户确认（auto_confirm_extract默认False）
4. ✅ Q4: 预留converters接口
5. ✅ Q5: 重试2次，失败后降级，再失败后中断
