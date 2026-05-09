"""人物形象设计Agent - 团队美术师

负责设计角色的视觉形象，确保长上下文中的人物一致性。
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from agents.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class CharacterDesign:
    """角色设计"""
    character_id: str
    name: str
    role: str
    personality_description: str
    appearance_description: str          # 详细外貌描述
    signature_features: List[str]        # 标志性特征
    clothing_description: str            # 服装描述
    typical_actions: List[str]           # 典型动作
    seedance_prompt: str                 # Seedance视频生成提示词
    image_prompts: Dict[str, str]        # 多角度图像提示词
    style_guide: str                     # 风格指南

    def to_dict(self) -> Dict[str, Any]:
        return {
            'character_id': self.character_id,
            'name': self.name,
            'role': self.role,
            'personality_description': self.personality_description,
            'appearance_description': self.appearance_description,
            'signature_features': self.signature_features,
            'clothing_description': self.clothing_description,
            'typical_actions': self.typical_actions,
            'seedance_prompt': self.seedance_prompt,
            'image_prompts': self.image_prompts,
            'style_guide': self.style_guide
        }


@dataclass
class FullCharacterDesigns:
    """完整角色设计集"""
    characters: List[CharacterDesign]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'characters': [char.to_dict() for char in self.characters]
        }

    def get_character(self, name: str) -> Optional[CharacterDesign]:
        """根据名称获取角色设计"""
        for char in self.characters:
            if char.name == name:
                return char
        return None


class CharacterDesignAgent:
    """人物形象设计Agent

    职责：
    1. 设计角色的详细外貌描述
    2. 定义标志性特征，确保一致性
    3. 生成多角度图像提示词
    4. 生成Seedance视频生成提示词

    Input: 角色设定列表
    Output: FullCharacterDesigns
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def design(self, characters: List[Dict[str, Any]],
                     visual_style: str = "") -> FullCharacterDesigns:
        """设计所有角色

        Args:
            characters: 角色设定列表
            visual_style: 整体视觉风格

        Returns:
            FullCharacterDesigns实例
        """
        logger.info(f"Designing {len(characters)} characters")

        designs = []

        # 逐个设计角色
        for char in characters:
            logger.info(f"Designing character: {char.get('name', 'Unknown')}")
            design = await self._design_character(char, visual_style)
            designs.append(design)

        return FullCharacterDesigns(characters=designs)

    async def _design_character(self, character: Dict[str, Any],
                                visual_style: str) -> CharacterDesign:
        """设计单个角色"""
        prompt = self._build_character_prompt(character, visual_style)

        system_prompt = """你是一位专业的影视人物美术设计师，擅长设计特征明确、可保证生成一致性的短剧人物形象。

设计要求：
1. 人设描述必须精准、可量化，无模糊词汇
2. 所有内容可直接转化为图像生成提示词
3. 必须设计标志性特征，确保不同镜头中的人物一致性
4. 服化道设计必须贴合角色设定和场景需求

输出必须是有效的JSON格式。"""

        result = await self.llm.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.7
        )

        return self._parse_character_design(result, character)

    def _build_character_prompt(self, character: Dict[str, Any],
                                visual_style: str) -> str:
        """构建角色设计提示词"""
        personality = ', '.join(character.get('personality', []))

        return f"""请为以下角色设计详细的视觉形象：

## 角色信息
- 姓名：{character.get('name', '未命名')}
- 角色定位：{character.get('role', 'supporting')}
- 描述：{character.get('description', '')}
- 性格标签：{personality}
- 人物弧线：{character.get('arc', '')}
- 已有外貌描述：{character.get('appearance', '无')}

## 视觉风格
{visual_style if visual_style else '请根据角色设定自行设计合适的视觉风格'}

## 请输出以下JSON格式：

{{
    "personality_description": "性格的视觉化描述（如何通过外表和姿态体现性格）",
    "appearance_description": "详细的外貌描述（脸型、五官、肤色、发型、身材等，必须具体可量化）",
    "signature_features": ["标志性特征1", "标志性特征2"],
    "clothing_description": "服装描述（材质、颜色、款式、配饰等）",
    "typical_actions": ["典型动作1", "典型动作2", "典型动作3"],
    "seedance_prompt": "用于Seedance视频生成的角色提示词（包含外貌、服装、气质的完整描述）",
    "image_prompts": {{
        "front": "正面照提示词",
        "side_45": "45度侧面照提示词",
        "side_90": "90度侧面照提示词",
        "closeup": "特写照提示词",
        "fullbody": "全身照提示词"
    }},
    "style_guide": "角色风格指南（在不同场景中的视觉变化规则）"
}}

注意：
1. 外貌描述必须具体，避免"美丽"、"帅气"等模糊词汇
2. 标志性特征必须在每个镜头中都能体现
3. 提示词必须可直接用于AI图像/视频生成"""

    def _parse_character_design(self, result: Dict[str, Any],
                                character: Dict[str, Any]) -> CharacterDesign:
        """解析LLM输出为CharacterDesign"""
        return CharacterDesign(
            character_id=character.get('id', ''),
            name=character.get('name', ''),
            role=character.get('role', ''),
            personality_description=result.get('personality_description', ''),
            appearance_description=result.get('appearance_description', ''),
            signature_features=result.get('signature_features', []),
            clothing_description=result.get('clothing_description', ''),
            typical_actions=result.get('typical_actions', []),
            seedance_prompt=result.get('seedance_prompt', ''),
            image_prompts=result.get('image_prompts', {}),
            style_guide=result.get('style_guide', '')
        )
