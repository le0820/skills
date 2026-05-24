# InkOS + Seedance 管线串联方案

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Creative Pipeline Orchestrator                      │
│                              (编排层)                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐              │
│  │   灵感输入    │      │   视频输入    │      │   文本输入    │              │
│  │  (Inspiration)│      │   (Video)    │      │   (Text)     │              │
│  └──────┬───────┘      └──────┬───────┘      └──────┬───────┘              │
│         │                     │                     │                       │
│         ▼                     ▼                     ▼                       │
│  ┌─────────────────────────────────────────────────────────┐                │
│  │              Unified Story Schema (统一故事格式)          │                │
│  │    { plot, characters, conflicts, turning_points }       │                │
│  └─────────────────────────┬───────────────────────────────┘                │
│                            │                                                │
│         ┌──────────────────┼──────────────────┐                             │
│         ▼                  ▼                  ▼                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │   Novel Mode │  │  Drama Mode  │  │  Hybrid Mode │                      │
│  │  (小说模式)   │  │  (短剧模式)   │  │  (混合模式)   │                      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                      │
│         │                 │                  │                              │
│         ▼                 ▼                  ▼                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │    InkOS     │  │   Seedance   │  │  InkOS →     │                      │
│  │   Pipeline   │  │   Pipeline   │  │  Seedance    │                      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                      │
│         │                 │                  │                              │
│         ▼                 ▼                  ▼                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │  Novel/Book  │  │ Screenplay + │  │  Novel +     │                      │
│  │              │  │ Video Prompts│  │  Video Prompts│                      │
│  └──────────────┘  └──────────────┘  └──────────────┘                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 1. 统一故事格式 (Unified Story Schema)

两个管线通过统一的JSON格式进行数据交换：

```typescript
interface UnifiedStory {
  // 元数据
  id: string;
  title: string;
  mode: 'novel' | 'drama' | 'hybrid';
  target_market: 'china' | 'west' | 'india' | 'latam' | 'global';
  language: 'zh' | 'en' | 'hi' | 'es' | 'pt';

  // 核心内容
  premise: string;           // 一句话前提
  logline: string;           // 一句话故事线
  genre: string;             // 题材类型
  themes: string[];          // 主题列表

  // 人物
  characters: Character[];

  // 剧情结构
  plot: {
    act1: PlotPoint[];       // 第一幕
    act2: PlotPoint[];       // 第二幕
    act3: PlotPoint[];       // 第三幕
  };

  // 冲突与转折
  conflicts: Conflict[];
  turning_points: TurningPoint[];

  // 风格配置
  style: {
    tone: string;            // 语调
    pacing: string;          // 节奏
    visual_style?: string;   // 视觉风格（用于视频生成）
  };

  // 输出配置
  output: {
    chapters?: number;       // 小说章节数
    episodes?: number;       // 短剧集数
    words_per_chapter?: number;
    seconds_per_episode?: number;
  };
}

interface Character {
  id: string;
  name: string;
  role: 'protagonist' | 'antagonist' | 'supporting';
  description: string;
  personality: string[];
  appearance?: string;       // 外貌描述（用于视频生成）
  arc: string;               // 人物弧线
  relationships: { character_id: string; relation: string }[];
}

interface PlotPoint {
  id: string;
  event: string;
  purpose: string;
  characters_involved: string[];
  emotional_beat: string;
  location?: string;
}

interface Conflict {
  id: string;
  type: 'internal' | 'external' | 'relationship' | 'societal';
  description: string;
  characters_involved: string[];
  resolution?: string;
}

interface TurningPoint {
  id: string;
  event: string;
  impact: string;
  chapter_or_episode: number;
}
```

## 2. 管线编排层设计

### 2.1 Orchestrator 模块

```python
# orchestrator.py - 编排器核心

class CreativeOrchestrator:
    """创意管线编排器"""

    def __init__(self, inkos_path: str, seedance_path: str):
        self.inkos = InkOSClient(inkos_path)
        self.seedance = SeedanceClient(seedance_path)
        self.schema = UnifiedStorySchema()

    async def run_pipeline(self, input_data: dict, mode: str) -> dict:
        """运行完整的创意管线"""

        # 1. 解析输入
        story = self.schema.parse(input_data)

        # 2. 根据模式选择管线
        if mode == 'novel':
            return await self._run_novel_pipeline(story)
        elif mode == 'drama':
            return await self._run_drama_pipeline(story)
        elif mode == 'hybrid':
            return await self._run_hybrid_pipeline(story)
        else:
            raise ValueError(f"Unknown mode: {mode}")

    async def _run_novel_pipeline(self, story: UnifiedStory) -> dict:
        """小说模式：完整小说生成"""
        # 利用 InkOS 生成小说
        result = await self.inkos.create_book(
            title=story.title,
            genre=story.genre,
            chapter_words=story.output.words_per_chapter
        )

        # 写入大纲和人物设定
        await self.inkos.write_chapters(
            book_id=result['book_id'],
            count=story.output.chapters,
            context=self._generate_novel_context(story)
        )

        return {
            'type': 'novel',
            'book_id': result['book_id'],
            'output_path': await self.inkos.export(result['book_id'])
        }

    async def _run_drama_pipeline(self, story: UnifiedStory) -> dict:
        """短剧模式：剧本+视频提示词生成"""
        # 利用 Seedance 生成剧本和提示词
        result = await self.seedance.generate_screenplay(
            story=self.schema.to_dict(story),
            episodes=story.output.episodes,
            seconds_per_episode=story.output.seconds_per_episode
        )

        return {
            'type': 'drama',
            'screenplay': result['screenplay'],
            'video_prompts': result['video_prompts'],
            'character_designs': result['character_designs']
        }

    async def _run_hybrid_pipeline(self, story: UnifiedStory) -> dict:
        """混合模式：小说 → 短剧"""
        # 先生成小说
        novel_result = await self._run_novel_pipeline(story)

        # 从小说中提取剧本素材
        novel_content = await self.inkos.export(novel_result['book_id'])
        screenplay_input = self._extract_screenplay_elements(novel_content)

        # 生成短剧
        drama_result = await self._run_drama_pipeline(screenplay_input)

        return {
            'type': 'hybrid',
            'novel': novel_result,
            'drama': drama_result
        }

    def _generate_novel_context(self, story: UnifiedStory) -> str:
        """生成小说写作上下文"""
        context_parts = [
            f"故事前提：{story.premise}",
            f"故事线：{story.logline}",
            f"主题：{', '.join(story.themes)}",
            "\n主要人物："
        ]

        for char in story.characters:
            context_parts.append(
                f"- {char.name}（{char.role}）：{char.description}"
            )

        context_parts.append("\n核心冲突：")
        for conflict in story.conflicts:
            context_parts.append(f"- {conflict.description}")

        return '\n'.join(context_parts)

    def _extract_screenplay_elements(self, novel_content: str) -> UnifiedStory:
        """从小说中提取剧本元素"""
        # 利用LLM从小说中提取关键元素
        # 返回适合剧本生成的UnifiedStory
        pass
```

## 3. InkOS 接口扩展

### 3.1 新增命令支持

```bash
# 从统一格式创建书籍
inkos book create --from-schema story.json

# 导出为统一格式
inkos export book-id --format unified-schema

# 为剧本生成提取素材
inkos extract book-id --for screenplay
```

### 3.2 InkOS 客户端

```python
# inkos_client.py

class InkOSClient:
    """InkOS CLI 客户端"""

    def __init__(self, base_path: str):
        self.base_path = base_path

    async def create_book(self, title: str, genre: str,
                          chapter_words: int = 3000) -> dict:
        """创建新书"""
        result = await self._run_command(
            f"inkos book create --title '{title}' --genre {genre} "
            f"--chapter-words {chapter_words} --json"
        )
        return json.loads(result)

    async def write_chapters(self, book_id: str, count: int,
                             context: str = None) -> dict:
        """写入章节"""
        cmd = f"inkos write next {book_id} --count {count}"
        if context:
            cmd += f" --context '{context}'"
        cmd += " --json"

        result = await self._run_command(cmd)
        return json.loads(result)

    async def export(self, book_id: str,
                     format: str = 'txt') -> str:
        """导出书籍"""
        result = await self._run_command(
            f"inkos export {book_id} --format {format}"
        )
        return result

    async def get_truth_files(self, book_id: str) -> dict:
        """获取真相文件"""
        result = await self._run_command(
            f"inkos status {book_id} --json"
        )
        return json.loads(result)

    async def _run_command(self, cmd: str) -> str:
        """执行CLI命令"""
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed: {stderr.decode()}")
        return stdout.decode()
```

## 4. Seedance 模块实现

### 4.1 Seedance Agent 系统

```python
# seedance/agents/seedance_system.py

class SeedanceAgentSystem:
    """Seedance 多Agent协同系统"""

    def __init__(self, llm_config: dict):
        self.llm = LLMClient(llm_config)

        # 初始化各个Agent
        self.director = DirectorAgent(self.llm)
        self.screenplay = ScreenplayAgent(self.llm)
        self.character_design = CharacterDesignAgent(self.llm)
        self.action_design = ActionDesignAgent(self.llm)
        self.prompt_engineer = PromptEngineerAgent(self.llm)

    async def generate_screenplay(self, story: dict,
                                   episodes: int = 5,
                                   seconds_per_episode: int = 60) -> dict:
        """生成完整剧本和视频提示词"""

        # 1. 总导演拆解需求
        project_plan = await self.director.create_project(
            story=story,
            episodes=episodes,
            seconds_per_episode=seconds_per_episode
        )

        # 2. 剧本创作（并行执行）
        screenplay_task = self.screenplay.write(
            plan=project_plan,
            story=story
        )

        # 3. 人物形象设计（并行执行）
        character_task = self.character_design.design(
            characters=story['characters']
        )

        # 等待并行任务完成
        screenplay, character_designs = await asyncio.gather(
            screenplay_task,
            character_task
        )

        # 4. 动作与镜头设计
        action_design = await self.action_design.design(
            screenplay=screenplay,
            character_designs=character_designs
        )

        # 5. 提示词工程
        video_prompts = await self.prompt_engineer.generate(
            screenplay=screenplay,
            character_designs=character_designs,
            action_design=action_design
        )

        return {
            'project_plan': project_plan,
            'screenplay': screenplay,
            'character_designs': character_designs,
            'action_design': action_design,
            'video_prompts': video_prompts
        }
```

### 4.2 从 InkOS 真相文件提取剧本素材

```python
# seedance/extractors/novel_extractor.py

class NovelExtractor:
    """从小说中提取剧本素材"""

    def __init__(self, llm_client):
        self.llm = llm_client

    async def extract_for_screenplay(self, novel_content: str,
                                      truth_files: dict) -> dict:
        """从小说内容和真相文件中提取剧本素材"""

        # 1. 提取场景
        scenes = await self._extract_scenes(novel_content)

        # 2. 提取对话
        dialogues = await self._extract_dialogues(novel_content)

        # 3. 提取冲突点
        conflicts = await self._extract_conflicts(
            novel_content,
            truth_files.get('subplot_board.md', '')
        )

        # 4. 提取人物弧线
        character_arcs = truth_files.get('emotional_arcs.md', '')

        # 5. 构建剧本结构
        screenplay_structure = await self._build_screenplay_structure(
            scenes=scenes,
            dialogues=dialogues,
            conflicts=conflicts,
            character_arcs=character_arcs
        )

        return screenplay_structure

    async def _extract_scenes(self, content: str) -> list:
        """提取场景"""
        prompt = """
        从小说文本中提取所有场景，每个场景包含：
        - 场景描述
        - 地点
        - 时间
        - 出场人物
        - 主要事件
        - 情绪基调

        小说内容：
        {content}

        请以JSON格式输出。
        """
        result = await self.llm.generate(prompt.format(content=content))
        return json.loads(result)
```

## 5. 完整工作流示例

### 5.1 从灵感到小说

```python
async def inspiration_to_novel(inspiration: str):
    """从灵感到小说"""

    orchestrator = CreativeOrchestrator(
        inkos_path="/path/to/inkos",
        seedance_path="/path/to/seedance"
    )

    # 定义故事
    story = {
        'title': '星际觉醒',
        'mode': 'novel',
        'target_market': 'china',
        'language': 'zh',
        'premise': inspiration,
        'genre': 'xuanhuan',
        'output': {
            'chapters': 20,
            'words_per_chapter': 3000
        }
    }

    # 运行管线
    result = await orchestrator.run_pipeline(story, mode='novel')
    return result
```

### 5.2 从灵感到短剧

```python
async def inspiration_to_drama(inspiration: str):
    """从灵感到短剧"""

    orchestrator = CreativeOrchestrator(
        inkos_path="/path/to/inkos",
        seedance_path="/path/to/seedance"
    )

    # 定义故事
    story = {
        'title': '都市逆袭',
        'mode': 'drama',
        'target_market': 'west',
        'language': 'en',
        'premise': inspiration,
        'genre': 'urban',
        'output': {
            'episodes': 10,
            'seconds_per_episode': 60
        }
    }

    # 运行管线
    result = await orchestrator.run_pipeline(story, mode='drama')
    return result
```

### 5.3 混合模式（小说+短剧）

```python
async def inspiration_to_hybrid(inspiration: str):
    """从灵感到小说+短剧"""

    orchestrator = CreativeOrchestrator(
        inkos_path="/path/to/inkos",
        seedance_path="/path/to/seedance"
    )

    # 定义故事
    story = {
        'title': '赛博朋克：新纪元',
        'mode': 'hybrid',
        'target_market': 'global',
        'language': 'en',
        'premise': inspiration,
        'genre': 'other',
        'output': {
            'chapters': 10,
            'words_per_chapter': 3000,
            'episodes': 5,
            'seconds_per_episode': 90
        }
    }

    # 运行管线
    result = await orchestrator.run_pipeline(story, mode='hybrid')
    return result
```

## 6. 目录结构

```
scripts/writing/
├── seedance/
│   ├── orchestrator/           # 编排层
│   │   ├── __init__.py
│   │   ├── core.py            # 核心编排器
│   │   ├── schema.py          # 统一格式定义
│   │   └── clients/           # 管线客户端
│   │       ├── inkos_client.py
│   │       └── seedance_client.py
│   ├── agents/                # Seedance Agent 系统
│   │   ├── __init__.py
│   │   ├── director.py
│   │   ├── screenplay.py
│   │   ├── character_design.py
│   │   ├── action_design.py
│   │   └── prompt_engineer.py
│   ├── extractors/            # 内容提取器
│   │   ├── __init__.py
│   │   ├── novel_extractor.py
│   │   └── video_extractor.py
│   ├── converters/            # 格式转换器
│   │   ├── __init__.py
│   │   ├── style_converter.py
│   │   └── language_converter.py
│   └── main.py
├── inkos/                     # InkOS (已有)
└── PIPELINE_INTEGRATION.md    # 本文档
```

## 7. 快速开始

### 7.1 安装依赖

```bash
# 安装 InkOS
npm i -g @actalk/inkos

# 安装 Python 依赖
pip install -r requirements.txt
```

### 7.2 配置

```bash
# 配置 InkOS
inkos config set-global \
  --provider openai \
  --base-url https://api.openai.com/v1 \
  --api-key sk-xxx \
  --model gpt-4o

# 配置 Seedance
export LLM_API_KEY=sk-xxx
export LLM_MODEL=gpt-4o
```

### 7.3 使用示例

```python
from orchestrator import CreativeOrchestrator

# 初始化编排器
orchestrator = CreativeOrchestrator(
    inkos_path="./inkos",
    seedance_path="./seedance"
)

# 从灵感到小说
result = await orchestrator.run_pipeline(
    input_data={
        'title': '我的小说',
        'premise': '一个普通程序员意外获得超能力...',
        'mode': 'novel'
    },
    mode='novel'
)

# 从灵感到短剧
result = await orchestrator.run_pipeline(
    input_data={
        'title': '我的短剧',
        'premise': '一个外卖小哥穿越到古代...',
        'mode': 'drama'
    },
    mode='drama'
)
```

## 8. 下一步计划

1. **实现 Orchestrator 核心**：统一格式、管线调度
2. **实现 Seedance Agent 系统**：基于 POC 文档实现各 Agent
3. **实现提取器**：从小说中提取剧本素材
4. **实现转换器**：多语言风格转换
5. **集成测试**：端到端测试完整管线
