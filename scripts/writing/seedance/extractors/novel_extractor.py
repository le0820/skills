"""小说内容提取器 - 从小说中提取剧本素材

将InkOS生成的小说内容转换为Seedance可用的故事数据格式。
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from agents.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class ExtractedScene:
    """提取的场景"""
    location: str
    time_of_day: str
    description: str
    characters: List[str]
    events: List[str]
    emotional_beat: str


@dataclass
class ExtractedDialogue:
    """提取的对话"""
    character: str
    line: str
    emotion: str
    context: str


@dataclass
class ExtractedConflict:
    """提取的冲突"""
    type: str
    description: str
    characters_involved: List[str]
    resolution: Optional[str]


@dataclass
class ExtractedCharacter:
    """提取的角色"""
    name: str
    role: str
    description: str
    personality: List[str]
    appearance: str
    arc: str


@dataclass
class NovelExtractionResult:
    """小说提取结果"""
    title: str
    premise: str
    characters: List[ExtractedCharacter]
    scenes: List[ExtractedScene]
    dialogues: List[ExtractedDialogue]
    conflicts: List[ExtractedConflict]
    themes: List[str]

    def to_unified_story_dict(self, **kwargs) -> Dict[str, Any]:
        """转换为UnifiedStory格式的字典

        Args:
            **kwargs: 额外的UnifiedStory字段

        Returns:
            UnifiedStory格式的字典
        """
        return {
            'id': kwargs.get('id', ''),
            'title': self.title,
            'mode': kwargs.get('mode', 'drama'),
            'target_market': kwargs.get('target_market', 'global'),
            'language': kwargs.get('language', 'en'),
            'premise': self.premise,
            'logline': kwargs.get('logline', ''),
            'genre': kwargs.get('genre', 'other'),
            'themes': self.themes,
            'characters': [
                {
                    'id': f"char_{i}",
                    'name': char.name,
                    'role': char.role,
                    'description': char.description,
                    'personality': char.personality,
                    'appearance': char.appearance,
                    'arc': char.arc,
                    'relationships': []
                }
                for i, char in enumerate(self.characters)
            ],
            'plot_points': [
                {
                    'id': f"pp_{i}",
                    'event': scene.events[0] if scene.events else '',
                    'purpose': scene.emotional_beat,
                    'characters_involved': scene.characters,
                    'emotional_beat': scene.emotional_beat,
                    'location': scene.location
                }
                for i, scene in enumerate(self.scenes[:10])  # 限制数量
            ],
            'conflicts': [
                {
                    'id': f"conf_{i}",
                    'type': conflict.type,
                    'description': conflict.description,
                    'characters_involved': conflict.characters_involved,
                    'resolution': conflict.resolution
                }
                for i, conflict in enumerate(self.conflicts)
            ],
            'output': kwargs.get('output', {
                'episodes': 5,
                'seconds_per_episode': 60
            })
        }


class NovelExtractor:
    """小说内容提取器

    从小说文本中提取：
    - 角色信息
    - 场景描述
    - 对话内容
    - 冲突点
    - 主题

    Input: 小说文本 + InkOS真相文件
    Output: NovelExtractionResult
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def extract(self, novel_content: str,
                      truth_files: Optional[Dict[str, str]] = None) -> NovelExtractionResult:
        """从小说内容提取剧本素材

        Args:
            novel_content: 小说文本内容
            truth_files: InkOS真相文件字典（可选）

        Returns:
            NovelExtractionResult实例
        """
        logger.info("Extracting screenplay elements from novel")

        # 并行提取各元素
        characters_task = self._extract_characters(novel_content, truth_files)
        scenes_task = self._extract_scenes(novel_content)
        conflicts_task = self._extract_conflicts(novel_content, truth_files)
        themes_task = self._extract_themes(novel_content)

        characters, scenes, conflicts, themes = await asyncio.gather(
            characters_task,
            scenes_task,
            conflicts_task,
            themes_task
        )

        # 提取对话（依赖scenes结果）
        dialogues = await self._extract_dialogues(novel_content, scenes)

        # 生成前提
        premise = await self._generate_premise(novel_content)

        # 从真相文件获取标题
        title = "Extracted Story"
        if truth_files and 'chapter_summaries.md' in truth_files:
            # 尝试从摘要中提取标题
            first_line = truth_files['chapter_summaries.md'].split('\n')[0]
            if first_line.startswith('#'):
                title = first_line.lstrip('#').strip()

        return NovelExtractionResult(
            title=title,
            premise=premise,
            characters=characters,
            scenes=scenes,
            dialogues=dialogues,
            conflicts=conflicts,
            themes=themes
        )

    async def _extract_characters(self, content: str,
                                  truth_files: Optional[Dict[str, str]] = None) -> List[ExtractedCharacter]:
        """提取角色信息"""
        # 优先从真相文件提取
        character_matrix = ""
        if truth_files and 'character_matrix.md' in truth_files:
            character_matrix = truth_files['character_matrix.md']

        prompt = f"""请从小说文本中提取所有主要角色信息。

## 小说文本（前5000字）
{content[:5000]}

## 角色矩阵（如有）
{character_matrix[:2000] if character_matrix else '无'}

请以JSON格式输出角色列表：
{{
    "characters": [
        {{
            "name": "角色名",
            "role": "protagonist/antagonist/supporting",
            "description": "角色简介（50字以内）",
            "personality": ["性格1", "性格2"],
            "appearance": "外貌描述（100字以内）",
            "arc": "人物弧线（50字以内）"
        }}
    ]
}}

注意：
1. 只提取主要角色（最多5个）
2. 外貌描述要具体，用于视频生成
3. 人物弧线要体现成长变化"""

        system_prompt = "你是专业的文学分析师，擅长从文本中提取角色信息。输出必须是有效的JSON格式。"

        result = await self.llm.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.3
        )

        return [
            ExtractedCharacter(**char)
            for char in result.get('characters', [])
        ]

    async def _extract_scenes(self, content: str) -> List[ExtractedScene]:
        """提取场景信息"""
        prompt = f"""请从小说文本中提取关键场景（最多10个）。

## 小说文本（前5000字）
{content[:5000]}

请以JSON格式输出场景列表：
{{
    "scenes": [
        {{
            "location": "场景地点",
            "time_of_day": "白天/夜晚/黄昏等",
            "description": "场景描述（50字以内）",
            "characters": ["角色1", "角色2"],
            "events": ["事件1"],
            "emotional_beat": "情绪基调"
        }}
    ]
}}

注意：
1. 只提取关键场景
2. 场景描述要具象，可用于视频生成
3. 情绪基调要准确"""

        system_prompt = "你是专业的场景分析师，擅长从文本中提取场景信息。输出必须是有效的JSON格式。"

        result = await self.llm.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.3
        )

        return [
            ExtractedScene(**scene)
            for scene in result.get('scenes', [])
        ]

    async def _extract_dialogues(self, content: str,
                                 scenes: List[ExtractedScene]) -> List[ExtractedDialogue]:
        """提取对话信息"""
        prompt = f"""请从小说文本中提取重要对话（最多10段）。

## 小说文本（前5000字）
{content[:5000]}

请以JSON格式输出对话列表：
{{
    "dialogues": [
        {{
            "character": "说话角色",
            "line": "台词内容",
            "emotion": "情绪",
            "context": "对话背景（20字以内）"
        }}
    ]
}}

注意：
1. 只提取推动剧情的重要对话
2. 台词要口语化
3. 情绪要准确"""

        system_prompt = "你是专业的对话分析师，擅长从文本中提取对话信息。输出必须是有效的JSON格式。"

        result = await self.llm.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.3
        )

        return [
            ExtractedDialogue(**dialogue)
            for dialogue in result.get('dialogues', [])
        ]

    async def _extract_conflicts(self, content: str,
                                 truth_files: Optional[Dict[str, str]] = None) -> List[ExtractedConflict]:
        """提取冲突信息"""
        subplot_info = ""
        if truth_files and 'subplot_board.md' in truth_files:
            subplot_info = truth_files['subplot_board.md']

        prompt = f"""请从小说文本中提取核心冲突。

## 小说文本（前5000字）
{content[:5000]}

## 支线信息（如有）
{subplot_info[:2000] if subplot_info else '无'}

请以JSON格式输出冲突列表：
{{
    "conflicts": [
        {{
            "type": "internal/external/relationship/societal",
            "description": "冲突描述（50字以内）",
            "characters_involved": ["角色1", "角色2"],
            "resolution": "解决方式（如有）"
        }}
    ]
}}

注意：
1. 只提取核心冲突（最多5个）
2. 类型要准确分类
3. 描述要简洁有力"""

        system_prompt = "你是专业的剧情分析师，擅长从文本中提取冲突信息。输出必须是有效的JSON格式。"

        result = await self.llm.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.3
        )

        return [
            ExtractedConflict(**conflict)
            for conflict in result.get('conflicts', [])
        ]

    async def _extract_themes(self, content: str) -> List[str]:
        """提取主题"""
        prompt = f"""请从小说文本中提取核心主题（最多3个）。

## 小说文本（前3000字）
{content[:3000]}

请以JSON格式输出：
{{
    "themes": ["主题1", "主题2"]
}}

主题应该是抽象的概念，如"救赎"、"成长"、"背叛"等。"""

        system_prompt = "你是专业的文学分析师，擅长提炼作品主题。输出必须是有效的JSON格式。"

        result = await self.llm.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.3
        )

        return result.get('themes', [])

    async def _generate_premise(self, content: str) -> str:
        """生成一句话前提"""
        prompt = f"""请用一句话概括这个故事的核心前提（30字以内）。

## 小说文本（前2000字）
{content[:2000]}

请以JSON格式输出：
{{
    "premise": "一句话前提"
}}"""

        system_prompt = "你是专业的编剧，擅长提炼故事核心。输出必须是有效的JSON格式。"

        result = await self.llm.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.3
        )

        return result.get('premise', '')


# 需要导入asyncio
import asyncio
