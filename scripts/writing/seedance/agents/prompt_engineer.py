"""Seedance提示词工程Agent - 团队技术总监

负责将全链路内容整合为Seedance可直接使用的视频生成提示词。
"""

import json
import logging
from typing import Dict, Any, List
from dataclasses import dataclass, field

from agents.llm_client import LLMClient
from agents.screenplay import FullScreenplay
from agents.character_design import FullCharacterDesigns
from agents.action_design import FullActionDesign

logger = logging.getLogger(__name__)


@dataclass
class ShotPrompt:
    """单镜头提示词"""
    episode_number: int
    scene_number: int
    shot_number: int
    positive_prompt: str      # 正面提示词
    negative_prompt: str      # 负面提示词
    character_reference: str  # 角色参考图描述
    parameters: Dict[str, Any]  # 生成参数

    def to_dict(self) -> Dict[str, Any]:
        return {
            'episode_number': self.episode_number,
            'scene_number': self.scene_number,
            'shot_number': self.shot_number,
            'positive_prompt': self.positive_prompt,
            'negative_prompt': self.negative_prompt,
            'character_reference': self.character_reference,
            'parameters': self.parameters
        }


@dataclass
class EpisodePrompts:
    """单集提示词集"""
    episode_number: int
    shot_prompts: List[ShotPrompt]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'episode_number': self.episode_number,
            'shot_prompts': [sp.to_dict() for sp in self.shot_prompts]
        }


@dataclass
class FullVideoPrompts:
    """完整视频提示词"""
    title: str
    episodes: List[EpisodePrompts]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'episodes': [ep.to_dict() for ep in self.episodes]
        }

    def export_batch_format(self) -> List[Dict[str, Any]]:
        """导出为批量导入格式"""
        batch = []
        for ep in self.episodes:
            for sp in ep.shot_prompts:
                batch.append({
                    'episode': sp.episode_number,
                    'scene': sp.scene_number,
                    'shot': sp.shot_number,
                    'prompt': sp.positive_prompt,
                    'negative': sp.negative_prompt,
                    'params': sp.parameters
                })
        return batch


class PromptEngineerAgent:
    """Seedance提示词工程Agent

    职责：
    1. 整合全链路内容
    2. 按Seedance模板拼接提示词
    3. 适配Seedance模型特性
    4. 生成批量导入格式

    Input: FullScreenplay + FullCharacterDesigns + FullActionDesign
    Output: FullVideoPrompts
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def generate(self, screenplay: FullScreenplay,
                       character_designs: FullCharacterDesigns,
                       action_design: FullActionDesign) -> FullVideoPrompts:
        """生成完整视频提示词

        Args:
            screenplay: 完整剧本
            character_designs: 角色设计集
            action_design: 动作设计集

        Returns:
            FullVideoPrompts实例
        """
        logger.info(f"Generating video prompts for: {screenplay.title}")

        episodes_prompts = []

        for episode in screenplay.episodes:
            # 找到对应的动作用计
            episode_action = next(
                (ep for ep in action_design.episodes
                 if ep.episode_number == episode.episode_number),
                None
            )

            if episode_action:
                prompts = await self._generate_episode_prompts(
                    episode, character_designs, episode_action
                )
                episodes_prompts.append(prompts)

        return FullVideoPrompts(
            title=screenplay.title,
            episodes=episodes_prompts
        )

    async def _generate_episode_prompts(self, episode: 'EpisodeScreenplay',
                                        character_designs: FullCharacterDesigns,
                                        action_design: 'ActionDesignOutput') -> EpisodePrompts:
        """生成单集提示词"""
        # 构建镜头映射
        shot_map = {}
        for scene in episode.scenes:
            for shot in scene.shots:
                key = (scene.scene_number, shot.shot_number)
                shot_map[key] = {
                    'scene': scene,
                    'shot': shot
                }

        # 构建动作映射
        action_map = {}
        for detail in action_design.action_details:
            key = (detail.scene_number, detail.shot_number)
            action_map[key] = detail

        # 生成每个镜头的提示词
        shot_prompts = []
        for (scene_num, shot_num), shot_data in shot_map.items():
            action = action_map.get((scene_num, shot_num))
            prompt = await self._generate_shot_prompt(
                shot_data['scene'],
                shot_data['shot'],
                action,
                character_designs
            )
            shot_prompts.append(prompt)

        return EpisodePrompts(
            episode_number=episode.episode_number,
            shot_prompts=shot_prompts
        )

    async def _generate_shot_prompt(self, scene: 'Scene', shot: 'Shot',
                                    action: 'ActionDetail' = None,
                                    character_designs: FullCharacterDesigns = None) -> ShotPrompt:
        """生成单镜头提示词"""
        prompt = self._build_shot_prompt(scene, shot, action, character_designs)

        system_prompt = """你是专业的Seedance视频生成提示词工程师，擅长将影视内容整合为精准的视频提示词。

要求：
1. 提示词结构符合Seedance生成逻辑，核心元素前置
2. 必须包含人物一致性锁定元素
3. 适配竖屏9:16视频比例
4. 配套负面提示词，避免画面崩坏

输出必须是有效的JSON格式。"""

        result = await self.llm.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.5  # 低温度确保稳定性
        )

        return self._parse_shot_prompt(result, scene, shot)

    def _build_shot_prompt(self, scene: 'Scene', shot: 'Shot',
                           action: 'ActionDetail' = None,
                           character_designs: FullCharacterDesigns = None) -> str:
        """构建镜头提示词生成的提示"""
        # 角色信息
        characters_info = ""
        if character_designs:
            for char_name in shot.characters_present:
                char = character_designs.get_character(char_name)
                if char:
                    characters_info += f"""
角色 {char.name}：
- 外貌：{char.appearance_description[:150]}
- 标志性特征：{', '.join(char.signature_features)}
- 服装：{char.clothing_description[:100]}"""

        # 动作信息
        action_info = ""
        if action:
            action_info = f"""
动作设计：
- 角色动作：{json.dumps(action.character_actions, ensure_ascii=False)}
- 角色表情：{json.dumps(action.character_expressions, ensure_ascii=False)}
- 镜头细节：{action.camera_details}
- 情绪强度：{action.emotional_intensity}/10
- 动作提示词片段：{action.seedance_fragment}"""

        return f"""请为以下镜头生成Seedance视频提示词：

## 场景信息
- 地点：{scene.location}
- 时间：{scene.time_of_day}
- 场景描述：{scene.description}

## 镜头信息
- 景别：{shot.shot_type}
- 镜头角度：{shot.camera_angle}
- 镜头运动：{shot.camera_movement}
- 画面描述：{shot.scene_description}
- 台词：{shot.dialogue}
- 情绪：{shot.emotion}
- 出场角色：{', '.join(shot.characters_present)}
- 时长：{shot.duration_seconds}秒

## 角色设定
{characters_info}

## 动作设计
{action_info}

## 请输出以下JSON格式：

{{
    "positive_prompt": "正面提示词（整合场景、角色、动作、情绪、镜头的完整描述）",
    "negative_prompt": "负面提示词（避免的元素）",
    "character_reference": "角色参考图描述（用于一致性锁定）",
    "parameters": {{
        "aspect_ratio": "9:16",
        "duration_seconds": {shot.duration_seconds},
        "fps": 24,
        "style": "cinematic"
    }}
}}

注意：
1. 正面提示词结构：【人物主体 + 特征锁定 + 动作表情 + 镜头语言 + 服化道 + 场景光影 + 画质参数】
2. 核心元素前置，关键内容用()标注权重
3. 必须包含角色的标志性特征描述
4. 负面提示词要包含常见的画面崩坏元素"""

    def _parse_shot_prompt(self, result: Dict[str, Any],
                           scene: 'Scene', shot: 'Shot') -> ShotPrompt:
        """解析LLM输出为ShotPrompt"""
        return ShotPrompt(
            episode_number=0,  # 会在上层设置
            scene_number=scene.scene_number,
            shot_number=shot.shot_number,
            positive_prompt=result.get('positive_prompt', ''),
            negative_prompt=result.get('negative_prompt', ''),
            character_reference=result.get('character_reference', ''),
            parameters=result.get('parameters', {
                'aspect_ratio': '9:16',
                'duration_seconds': shot.duration_seconds,
                'fps': 24,
                'style': 'cinematic'
            })
        )
