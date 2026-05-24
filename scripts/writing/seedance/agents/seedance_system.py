"""Seedance Agent System - 多Agent协同系统

整合所有Agent，提供统一的剧本和视频提示词生成接口。
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from agents.llm_client import LLMClient, LLMConfig
from agents.director import DirectorAgent, ProjectPlan
from agents.screenplay import ScreenplayAgent, FullScreenplay
from agents.character_design import CharacterDesignAgent, FullCharacterDesigns
from agents.action_design import ActionDesignAgent, FullActionDesign
from .prompt_engineer import PromptEngineerAgent, FullVideoPrompts

logger = logging.getLogger(__name__)


@dataclass
class SeedanceOutput:
    """Seedance系统输出"""
    project_plan: ProjectPlan
    screenplay: FullScreenplay
    character_designs: FullCharacterDesigns
    action_design: FullActionDesign
    video_prompts: FullVideoPrompts

    def to_dict(self) -> Dict[str, Any]:
        return {
            'project_plan': self.project_plan.to_dict(),
            'screenplay': self.screenplay.to_dict(),
            'character_designs': self.character_designs.to_dict(),
            'action_design': self.action_design.to_dict(),
            'video_prompts': self.video_prompts.to_dict()
        }

    def get_prompts_batch(self) -> list:
        """获取批量导入格式的提示词"""
        return self.video_prompts.export_batch_format()


class SeedanceAgentSystem:
    """Seedance多Agent协同系统

    整合Director、Screenplay、CharacterDesign、ActionDesign、PromptEngineer五个Agent，
    提供端到端的剧本和视频提示词生成能力。

    执行流程：
    Director → [Screenplay ∥ CharacterDesign] → ActionDesign → PromptEngineer

    Example:
        system = SeedanceAgentSystem(llm_config)
        output = await system.generate(story_data)
    """

    def __init__(self, llm_config: Optional[LLMConfig] = None):
        """初始化系统

        Args:
            llm_config: LLM配置，为None时从环境变量加载
        """
        self.llm_client = LLMClient(llm_config)

        # 初始化所有Agent
        self.director = DirectorAgent(self.llm_client)
        self.screenplay = ScreenplayAgent(self.llm_client)
        self.character_design = CharacterDesignAgent(self.llm_client)
        self.action_design = ActionDesignAgent(self.llm_client)
        self.prompt_engineer = PromptEngineerAgent(self.llm_client)

    async def generate(self, story_data: Dict[str, Any]) -> SeedanceOutput:
        """生成完整剧本和视频提示词

        Args:
            story_data: UnifiedStory格式的故事数据

        Returns:
            SeedanceOutput实例，包含所有生成内容

        Raises:
            Exception: 生成失败
        """
        logger.info(f"Starting generation for: {story_data.get('title', 'Unknown')}")

        # Step 1: Director创建项目规划
        logger.info("Step 1: Director creating project plan")
        project_plan = await self.director.create_project(story_data)

        # Step 2: Screenplay和CharacterDesign并行执行
        logger.info("Step 2: Screenplay and CharacterDesign running in parallel")
        screenplay_task = self.screenplay.write(
            plan=project_plan,
            characters=story_data.get('characters', [])
        )

        character_task = self.character_design.design(
            characters=story_data.get('characters', []),
            visual_style=project_plan.visual_style
        )

        # 等待并行任务完成
        screenplay, character_designs = await asyncio.gather(
            screenplay_task,
            character_task
        )

        # Step 3: ActionDesign
        logger.info("Step 3: ActionDesign processing")
        action_design = await self.action_design.design(
            screenplay=screenplay,
            character_designs=character_designs
        )

        # Step 4: PromptEngineer
        logger.info("Step 4: PromptEngineer generating video prompts")
        video_prompts = await self.prompt_engineer.generate(
            screenplay=screenplay,
            character_designs=character_designs,
            action_design=action_design
        )

        logger.info("Generation complete")

        return SeedanceOutput(
            project_plan=project_plan,
            screenplay=screenplay,
            character_designs=character_designs,
            action_design=action_design,
            video_prompts=video_prompts
        )

    async def generate_screenplay_only(self, story_data: Dict[str, Any]) -> FullScreenplay:
        """只生成剧本（不生成视频提示词）

        Args:
            story_data: UnifiedStory格式的故事数据

        Returns:
            FullScreenplay实例
        """
        logger.info("Generating screenplay only")

        # 创建项目规划
        project_plan = await self.director.create_project(story_data)

        # 生成剧本
        screenplay = await self.screenplay.write(
            plan=project_plan,
            characters=story_data.get('characters', [])
        )

        return screenplay

    async def generate_character_designs(self, characters: list,
                                         visual_style: str = "") -> FullCharacterDesigns:
        """只生成角色设计

        Args:
            characters: 角色设定列表
            visual_style: 视觉风格

        Returns:
            FullCharacterDesigns实例
        """
        logger.info("Generating character designs only")

        return await self.character_design.design(
            characters=characters,
            visual_style=visual_style
        )

    async def close(self):
        """关闭系统，释放资源"""
        await self.llm_client.close()
