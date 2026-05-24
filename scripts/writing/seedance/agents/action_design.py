"""动作与镜头设计Agent - 团队动作指导+摄影指导

负责细化动作、表情、镜头语言，将模糊的情绪转化为具象的提示词片段。
"""

import json
import logging
from typing import Dict, Any, List
from dataclasses import dataclass, field

from agents.llm_client import LLMClient
from agents.screenplay import FullScreenplay, Shot
from agents.character_design import FullCharacterDesigns

logger = logging.getLogger(__name__)


@dataclass
class ActionDetail:
    """动作细化"""
    shot_number: int
    scene_number: int
    episode_number: int
    character_actions: Dict[str, str]      # 角色名 -> 动作描述
    character_expressions: Dict[str, str]  # 角色名 -> 表情描述
    camera_details: str                    # 镜头细节
    emotional_intensity: str               # 情绪强度
    seedance_fragment: str                 # Seedance提示词片段


@dataclass
class ActionDesignOutput:
    """动作设计输出"""
    episode_number: int
    action_details: List[ActionDetail]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'episode_number': self.episode_number,
            'action_details': [
                {
                    'shot_number': ad.shot_number,
                    'scene_number': ad.scene_number,
                    'episode_number': ad.episode_number,
                    'character_actions': ad.character_actions,
                    'character_expressions': ad.character_expressions,
                    'camera_details': ad.camera_details,
                    'emotional_intensity': ad.emotional_intensity,
                    'seedance_fragment': ad.seedance_fragment
                }
                for ad in self.action_details
            ]
        }


@dataclass
class FullActionDesign:
    """完整动作设计"""
    episodes: List[ActionDesignOutput]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'episodes': [ep.to_dict() for ep in self.episodes]
        }


class ActionDesignAgent:
    """动作与镜头设计Agent

    职责：
   1. 将分镜内容拆解为具象的肢体动作
    2. 细化镜头语言（景别、运镜、角度）
    3. 管理角色表情
    4. 生成Seedance友好的提示词片段

    Input: FullScreenplay + FullCharacterDesigns
    Output: FullActionDesign
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def design(self, screenplay: FullScreenplay,
                     character_designs: FullCharacterDesigns) -> FullActionDesign:
        """设计所有动作

        Args:
            screenplay: 完整剧本
            character_designs: 角色设计集

        Returns:
            FullActionDesign实例
        """
        logger.info("Designing actions for all episodes")

        episodes_design = []

        for episode in screenplay.episodes:
            logger.info(f"Designing actions for episode {episode.episode_number}")
            design = await self._design_episode(episode, character_designs)
            episodes_design.append(design)

        return FullActionDesign(episodes=episodes_design)

    async def _design_episode(self, episode: 'EpisodeScreenplay',
                              character_designs: FullCharacterDesigns) -> ActionDesignOutput:
        """设计单集动作"""
        # 收集所有镜头
        all_shots = []
        for scene in episode.scenes:
            for shot in scene.shots:
                all_shots.append({
                    'scene_number': scene.scene_number,
                    'location': scene.location,
                    'shot': shot
                })

        # 分批处理镜头（避免上下文过长）
        batch_size = 10
        action_details = []

        for i in range(0, len(all_shots), batch_size):
            batch = all_shots[i:i + batch_size]
            batch_result = await self._design_shot_batch(
                batch, character_designs, episode.episode_number
            )
            action_details.extend(batch_result)

        return ActionDesignOutput(
            episode_number=episode.episode_number,
            action_details=action_details
        )

    async def _design_shot_batch(self, shots: List[Dict[str, Any]],
                                 character_designs: FullCharacterDesigns,
                                 episode_number: int) -> List[ActionDetail]:
        """设计一批镜头的动作"""
        prompt = self._build_batch_prompt(shots, character_designs, episode_number)

        system_prompt = """你是一位专业的影视动作指导兼摄影指导，擅长为竖屏短剧设计精准、可落地的动作和镜头语言。

设计要求：
1. 所有动作描述必须具象、可量化，无模糊情绪词汇
2. 镜头设计适配竖屏9:16比例
3. 动作、表情必须贴合角色人设
4. 输出内容可直接用于视频生成提示词

输出必须是有效的JSON格式。"""

        result = await self.llm.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.7
        )

        return self._parse_action_details(result, shots, episode_number)

    def _build_batch_prompt(self, shots: List[Dict[str, Any]],
                            character_designs: FullCharacterDesigns,
                            episode_number: int) -> str:
        """构建批次提示词"""
        shots_info = []
        for item in shots:
            shot = item['shot']
            shots_info.append(f"""
镜头 {shot.shot_number}（场景 {item['scene_number']}，地点：{item['location']}）：
- 画面描述：{shot.scene_description}
- 镜头：{shot.shot_type}，{shot.camera_angle}，{shot.camera_movement}
- 动作：{shot.action}
- 台词：{shot.dialogue}
- 情绪：{shot.emotion}
- 出场角色：{', '.join(shot.characters_present)}
- 时长：{shot.duration_seconds}秒""")

        characters_info = []
        for char in character_designs.characters:
            characters_info.append(f"""
{char.name}（{char.role}）：
- 外貌：{char.appearance_description[:100]}...
- 标志性特征：{', '.join(char.signature_features)}
- 典型动作：{', '.join(char.typical_actions[:3])}""")

        return f"""请为以下镜头设计详细的动作和镜头语言：

## 剧集：第{episode_number}集

## 镜头列表
{''.join(shots_info)}

## 角色设定
{''.join(characters_info)}

## 请输出以下JSON格式：

{{
    "actions": [
        {{
            "shot_number": 1,
            "scene_number": 1,
            "character_actions": {{
                "角色名": "具体动作描述（如：右手握拳，身体微微前倾，向前迈步3步）"
            }},
            "character_expressions": {{
                "角色名": "表情描述（如：眉头紧锁，嘴角下撇，眼神锐利）"
            }},
            "camera_details": "镜头细节描述（焦距、光影、景深等）",
            "emotional_intensity": "情绪强度（1-10）",
            "seedance_fragment": "Seedance提示词片段（整合动作、表情、镜头的完整描述）"
        }}
    ]
}}

注意：
1. 动作描述必须具体，不要写"角色很生气"，要写"角色右手握拳，青筋暴起，身体前倾15度"
2. 表情要细化到微表情（眼神、眉毛、嘴角等）
3. Seedance片段要包含人物主体+动作+表情+镜头语言"""

    def _parse_action_details(self, result: Dict[str, Any],
                              shots: List[Dict[str, Any]],
                              episode_number: int) -> List[ActionDetail]:
        """解析LLM输出为ActionDetail列表"""
        details = []

        for action_data in result.get('actions', []):
            detail = ActionDetail(
                shot_number=action_data.get('shot_number', 0),
                scene_number=action_data.get('scene_number', 0),
                episode_number=episode_number,
                character_actions=action_data.get('character_actions', {}),
                character_expressions=action_data.get('character_expressions', {}),
                camera_details=action_data.get('camera_details', ''),
                emotional_intensity=action_data.get('emotional_intensity', '5'),
                seedance_fragment=action_data.get('seedance_fragment', '')
            )
            details.append(detail)

        return details
