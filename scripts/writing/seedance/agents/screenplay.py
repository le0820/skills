"""剧本创作Agent - 团队编剧

负责将项目规划转化为详细的分镜剧本。
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from agents.llm_client import LLMClient
from agents.director import ProjectPlan

logger = logging.getLogger(__name__)


@dataclass
class Shot:
    """单镜头"""
    shot_number: int
    scene_description: str       # 场景描述
    camera_angle: str           # 镜头角度
    camera_movement: str        # 镜头运动
    shot_type: str              # 景别（特写/中景/全景等）
    action: str                 # 动作描述
    dialogue: str               # 台词
    emotion: str                # 情绪
    duration_seconds: float     # 时长
    characters_present: List[str]  # 出场角色


@dataclass
class Scene:
    """场景"""
    scene_number: int
    location: str               # 地点
    time_of_day: str            # 时间
    description: str            # 场景描述
    shots: List[Shot]
    characters: List[str]       # 出场角色


@dataclass
class EpisodeScreenplay:
    """单集剧本"""
    episode_number: int
    title: str
    scenes: List[Scene]
    total_duration_seconds: float
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            'episode_number': self.episode_number,
            'title': self.title,
            'total_duration_seconds': self.total_duration_seconds,
            'summary': self.summary,
            'scenes': [
                {
                    'scene_number': scene.scene_number,
                    'location': scene.location,
                    'time_of_day': scene.time_of_day,
                    'description': scene.description,
                    'characters': scene.characters,
                    'shots': [
                        {
                            'shot_number': shot.shot_number,
                            'scene_description': shot.scene_description,
                            'camera_angle': shot.camera_angle,
                            'camera_movement': shot.camera_movement,
                            'shot_type': shot.shot_type,
                            'action': shot.action,
                            'dialogue': shot.dialogue,
                            'emotion': shot.emotion,
                            'duration_seconds': shot.duration_seconds,
                            'characters_present': shot.characters_present
                        }
                        for shot in scene.shots
                    ]
                }
                for scene in self.scenes
            ]
        }


@dataclass
class FullScreenplay:
    """完整剧本"""
    title: str
    episodes: List[EpisodeScreenplay]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'episodes': [ep.to_dict() for ep in self.episodes]
        }


class ScreenplayAgent:
    """剧本创作Agent

    职责：
    1. 将项目规划转化为详细分镜
    2. 设计场景和镜头
    3. 编写台词
    4. 控制节奏和时长

    Input: ProjectPlan + 角色设定
    Output: FullScreenplay
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def write(self, plan: ProjectPlan,
                    characters: List[Dict[str, Any]]) -> FullScreenplay:
        """编写完整剧本

        Args:
            plan: 项目规划
            characters: 角色设定列表

        Returns:
            FullScreenplay实例
        """
        logger.info(f"Writing screenplay for: {plan.title}")

        episodes_screenplay = []

        # 逐集生成剧本
        for episode in plan.episodes:
            logger.info(f"Writing episode {episode.episode_number}: {episode.title}")
            screenplay = await self._write_episode(
                plan=plan,
                episode=episode,
                characters=characters
            )
            episodes_screenplay.append(screenplay)

        return FullScreenplay(
            title=plan.title,
            episodes=episodes_screenplay
        )

    async def _write_episode(self, plan: ProjectPlan,
                             episode: 'Episode',
                             characters: List[Dict[str, Any]]) -> EpisodeScreenplay:
        """编写单集剧本"""
        prompt = self._build_episode_prompt(plan, episode, characters)

        system_prompt = """你是一位专业的竖屏短剧编剧，擅长将故事大纲转化为高传播度的分镜剧本。

创作要求：
1. 单集时长严格控制在指定秒数内
2. 单个镜头时长3-10秒
3. 强冲突、快节奏，抓住观众注意力
4. 台词口语化，符合目标市场语言习惯
5. 每个镜头必须明确：场景、镜头运动、画面内容、台词、情绪

输出必须是有效的JSON格式。"""

        result = await self.llm.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.8
        )

        return self._parse_episode(result, episode)

    def _build_episode_prompt(self, plan: ProjectPlan,
                              episode: 'Episode',
                              characters: List[Dict[str, Any]]) -> str:
        """构建单集提示词"""
        characters_info = ""
        for char in characters:
            characters_info += f"""
- {char['name']}（{char['role']}）：{char.get('description', '')}
  性格：{', '.join(char.get('personality', []))}
  外貌：{char.get('appearance', '未指定')}"""

        return f"""请为以下短剧集编写详细的分镜剧本：

## 剧集信息
- 标题：{plan.title} - 第{episode.episode_number}集：{episode.title}
- 集数：第{episode.episode_number}集
- 时长要求：{episode.duration_seconds}秒
- 风格：{plan.visual_style}
- 语调：{plan.tone}
- 目标市场：{plan.target_market}

## 剧情概要
{episode.summary}

## 关键事件
{json.dumps(episode.key_events, ensure_ascii=False)}

## 情绪弧线
{episode.emotional_arc}

## 角色设定
{characters_info}

## 角色弧线
{json.dumps(plan.character_arcs, ensure_ascii=False)}

## 请输出以下JSON格式：

{{
    "title": "{episode.title}",
    "summary": "本集概要",
    "scenes": [
        {{
            "scene_number": 1,
            "location": "场景地点",
            "time_of_day": "白天/夜晚/黄昏等",
            "description": "场景描述",
            "characters": ["角色1", "角色2"],
            "shots": [
                {{
                    "shot_number": 1,
                    "scene_description": "画面描述",
                    "camera_angle": "平视/俯视/仰视等",
                    "camera_movement": "固定/推进/拉远/横移/跟拍等",
                    "shot_type": "特写/近景/中景/全景/远景",
                    "action": "角色动作描述",
                    "dialogue": "台词（如有）",
                    "emotion": "情绪基调",
                    "duration_seconds": 5,
                    "characters_present": ["出场角色"]
                }}
            ]
        }}
    ]
}}

注意：
1. 总时长必须控制在{episode.duration_seconds}秒左右
2. 每个镜头3-10秒
3. 台词要口语化，符合{plan.target_market}市场习惯
4. 动作描述要具体，可直接用于视频生成"""

    def _parse_episode(self, result: Dict[str, Any],
                       episode: 'Episode') -> EpisodeScreenplay:
        """解析LLM输出为EpisodeScreenplay"""
        scenes = []
        total_duration = 0

        for scene_data in result.get('scenes', []):
            shots = []
            for shot_data in scene_data.get('shots', []):
                shot = Shot(
                    shot_number=shot_data.get('shot_number', 0),
                    scene_description=shot_data.get('scene_description', ''),
                    camera_angle=shot_data.get('camera_angle', '平视'),
                    camera_movement=shot_data.get('camera_movement', '固定'),
                    shot_type=shot_data.get('shot_type', '中景'),
                    action=shot_data.get('action', ''),
                    dialogue=shot_data.get('dialogue', ''),
                    emotion=shot_data.get('emotion', ''),
                    duration_seconds=shot_data.get('duration_seconds', 5),
                    characters_present=shot_data.get('characters_present', [])
                )
                shots.append(shot)
                total_duration += shot.duration_seconds

            scene = Scene(
                scene_number=scene_data.get('scene_number', 0),
                location=scene_data.get('location', ''),
                time_of_day=scene_data.get('time_of_day', ''),
                description=scene_data.get('description', ''),
                shots=shots,
                characters=scene_data.get('characters', [])
            )
            scenes.append(scene)

        return EpisodeScreenplay(
            episode_number=episode.episode_number,
            title=result.get('title', episode.title),
            scenes=scenes,
            total_duration_seconds=total_duration,
            summary=result.get('summary', episode.summary)
        )
