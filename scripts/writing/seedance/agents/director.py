"""总导演Agent - 全项目的核心枢纽

负责需求拆解、任务调度、冲突仲裁、全局记忆管理。
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from agents.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class Episode:
    """单集规划"""
    episode_number: int
    title: str
    summary: str
    key_events: List[str]
    emotional_arc: str
    duration_seconds: int


@dataclass
class ProjectPlan:
    """项目规划"""
    title: str
    logline: str
    genre: str
    target_market: str
    language: str
    episodes: List[Episode]
    character_arcs: Dict[str, str]  # character_id -> arc description
    themes: List[str]
    visual_style: str
    tone: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'logline': self.logline,
            'genre': self.genre,
            'target_market': self.target_market,
            'language': self.language,
            'episodes': [
                {
                    'episode_number': ep.episode_number,
                    'title': ep.title,
                    'summary': ep.summary,
                    'key_events': ep.key_events,
                    'emotional_arc': ep.emotional_arc,
                    'duration_seconds': ep.duration_seconds
                }
                for ep in self.episodes
            ],
            'character_arcs': self.character_arcs,
            'themes': self.themes,
            'visual_style': self.visual_style,
            'tone': self.tone
        }


class DirectorAgent:
    """总导演Agent

    职责：
    1. 解析用户需求，生成项目规划
    2. 拆解剧集结构
    3. 规划人物弧线
    4. 确定视觉风格和语调

    Input: UnifiedStory数据
    Output: ProjectPlan
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def create_project(self, story_data: Dict[str, Any]) -> ProjectPlan:
        """创建项目规划

        Args:
            story_data: UnifiedStory格式的故事数据

        Returns:
            ProjectPlan实例
        """
        logger.info(f"Creating project plan for: {story_data.get('title', 'Unknown')}")

        # 构建提示词
        prompt = self._build_planning_prompt(story_data)

        system_prompt = """你是一位经验丰富的短剧总导演，擅长将故事创意转化为可执行的项目规划。

你的任务是：
1. 理解故事核心，提炼出引人入胜的logline
2. 规划剧集结构，确保节奏紧凑
3. 设计人物弧线，确保角色成长
4. 确定视觉风格，适配目标市场

输出必须是有效的JSON格式。"""

        # 调用LLM生成规划
        result = await self.llm.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.7
        )

        # 解析结果
        return self._parse_plan(result, story_data)

    def _build_planning_prompt(self, story_data: Dict[str, Any]) -> str:
        """构建规划提示词"""
        episodes_count = story_data.get('output', {}).get('episodes', 5)
        seconds_per_episode = story_data.get('output', {}).get('seconds_per_episode', 60)

        characters_info = ""
        for char in story_data.get('characters', []):
            characters_info += f"""
- {char['name']}（{char['role']}）：{char['description']}
  性格：{', '.join(char.get('personality', []))}
  弧线：{char.get('arc', '待设计')}"""

        conflicts_info = ""
        for conflict in story_data.get('conflicts', []):
            conflicts_info += f"\n- [{conflict['type']}] {conflict['description']}"

        return f"""请为以下短剧项目创建详细的项目规划：

## 故事信息
- 标题：{story_data.get('title', '未命名')}
- 前提：{story_data.get('premise', '')}
- 题材：{story_data.get('genre', 'other')}
- 目标市场：{story_data.get('target_market', 'global')}
- 语言：{story_data.get('language', 'en')}

## 输出要求
- 集数：{episodes_count}集
- 每集时长：{seconds_per_episode}秒

## 角色设定
{characters_info if characters_info else '待设计'}

## 核心冲突
{conflicts_info if conflicts_info else '待设计'}

## 请输出以下JSON格式：

{{
    "logline": "一句话故事线（50字以内）",
    "themes": ["主题1", "主题2"],
    "visual_style": "视觉风格描述",
    "tone": "语调描述",
    "episodes": [
        {{
            "episode_number": 1,
            "title": "集标题",
            "summary": "剧情概要",
            "key_events": ["事件1", "事件2"],
            "emotional_arc": "情绪弧线",
            "duration_seconds": {seconds_per_episode}
        }}
    ],
    "character_arcs": {{
        "角色名": "角色弧线描述"
    }}
}}"""

    def _parse_plan(self, result: Dict[str, Any], story_data: Dict[str, Any]) -> ProjectPlan:
        """解析LLM输出为ProjectPlan"""
        episodes = []
        for ep_data in result.get('episodes', []):
            episodes.append(Episode(
                episode_number=ep_data.get('episode_number', 0),
                title=ep_data.get('title', ''),
                summary=ep_data.get('summary', ''),
                key_events=ep_data.get('key_events', []),
                emotional_arc=ep_data.get('emotional_arc', ''),
                duration_seconds=ep_data.get('duration_seconds', 60)
            ))

        return ProjectPlan(
            title=story_data.get('title', '未命名'),
            logline=result.get('logline', story_data.get('logline', '')),
            genre=story_data.get('genre', 'other'),
            target_market=story_data.get('target_market', 'global'),
            language=story_data.get('language', 'en'),
            episodes=episodes,
            character_arcs=result.get('character_arcs', {}),
            themes=result.get('themes', story_data.get('themes', [])),
            visual_style=result.get('visual_style', ''),
            tone=result.get('tone', '')
        )
