"""Creative Orchestrator - 创意管线编排器

协调InkOS和Seedance两个管线，提供统一的内容生成入口。
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from orchestrator.schema import UnifiedStory, RunMode, TargetMarket, Language
from orchestrator.clients.inkos_client import InkOSClient, InkOSConfig
from agents.seedance_system import SeedanceAgentSystem, SeedanceOutput
from agents.llm_client import LLMConfig
from extractors.novel_extractor import NovelExtractor

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """管线配置"""
    inkos_config: Optional[InkOSConfig] = None
    seedance_llm_config: Optional[LLMConfig] = None
    extract_for_screenplay: bool = True   # 是否自动提取剧本素材
    auto_confirm_extract: bool = False    # 自动确认提取结果（Q3决策：需要用户确认）


@dataclass
class NovelResult:
    """小说生成结果"""
    book_id: str
    output_path: str
    chapter_count: int
    word_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            'book_id': self.book_id,
            'output_path': self.output_path,
            'chapter_count': self.chapter_count,
            'word_count': self.word_count
        }


@dataclass
class DramaResult:
    """短剧生成结果"""
    screenplay: Dict[str, Any]
    video_prompts: List[Dict[str, Any]]
    character_designs: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'screenplay': self.screenplay,
            'video_prompts': self.video_prompts,
            'character_designs': self.character_designs
        }


@dataclass
class HybridResult:
    """混合模式结果"""
    novel: NovelResult
    drama: DramaResult

    def to_dict(self) -> Dict[str, Any]:
        return {
            'novel': self.novel.to_dict(),
            'drama': self.drama.to_dict()
        }


class CreativeOrchestrator:
    """创意管线编排器

    协调InkOS（小说生成）和Seedance（剧本+视频提示词生成），
    提供三种运行模式：
    - Novel模式：只生成小说
    - Drama模式：只生成剧本+视频提示词
    - Hybrid模式：小说→剧本+视频提示词

    Example:
        orchestrator = CreativeOrchestrator()
        result = await orchestrator.run_pipeline({
            'title': '我的故事',
            'premise': '一个程序员意外获得超能力...',
            'mode': 'novel'
        })
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        """初始化编排器

        Args:
            config: 管线配置，为None时使用默认配置
        """
        self.config = config or PipelineConfig()

        # 初始化客户端
        self.inkos = InkOSClient(self.config.inkos_config)
        self.seedance = SeedanceAgentSystem(self.config.seedance_llm_config)
        self.extractor = NovelExtractor(self.seedance.llm_client)

    async def run_pipeline(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """运行完整管线

        Args:
            input_data: 输入数据，包含：
                - title: 故事标题
                - premise: 故事前提
                - mode: 运行模式（novel/drama/hybrid）
                - target_market: 目标市场（可选）
                - language: 输出语言（可选）
                - genre: 题材（可选）
                - output: 输出配置（可选）

        Returns:
            包含生成结果的字典

        Raises:
            ValueError: 输入数据格式错误
            RuntimeError: 管线执行失败
        """
        # 解析输入
        story = self._parse_input(input_data)

        logger.info(f"Running pipeline in {story.mode.value} mode for: {story.title}")

        # 根据模式执行
        if story.mode == RunMode.NOVEL:
            result = await self._run_novel_pipeline(story)
            return {'mode': 'novel', 'result': result.to_dict()}

        elif story.mode == RunMode.DRAMA:
            result = await self._run_drama_pipeline(story)
            return {'mode': 'drama', 'result': result.to_dict()}

        elif story.mode == RunMode.HYBRID:
            result = await self._run_hybrid_pipeline(story)
            return {'mode': 'hybrid', 'result': result.to_dict()}

        else:
            raise ValueError(f"Unknown mode: {story.mode}")

    def _parse_input(self, input_data: Dict[str, Any]) -> UnifiedStory:
        """解析输入数据

        Args:
            input_data: 输入数据字典

        Returns:
            UnifiedStory实例

        Raises:
            ValueError: 缺少必填字段
        """
        # 生成默认ID
        if 'id' not in input_data:
            input_data['id'] = str(uuid.uuid4())

        # 设置默认值
        input_data.setdefault('mode', 'novel')
        input_data.setdefault('target_market', 'china')
        input_data.setdefault('language', 'zh')
        input_data.setdefault('genre', 'other')

        return UnifiedStory.from_dict(input_data)

    async def _run_novel_pipeline(self, story: UnifiedStory) -> NovelResult:
        """运行小说管线

        流程：
        1. 在InkOS中创建书籍
        2. 写入章节
        3. 导出小说
        """
        logger.info("Running novel pipeline")

        # Step 1: 创建书籍
        book_result = await self.inkos.create_book(
            title=story.title,
            genre=story.genre,
            chapter_words=story.output.words_per_chapter,
            target_chapters=story.output.chapters
        )

        book_id = book_result.get('bookId', book_result.get('book_id', book_result.get('id', '')))
        logger.info(f"Created book: {book_id}")

        # Step 2: 写入章节
        context = story.generate_novel_context()
        write_result = await self.inkos.write_chapters(
            book_id=book_id,
            count=story.output.chapters,
            context=context,
            words=story.output.words_per_chapter
        )

        logger.info(f"Written {story.output.chapters} chapters")

        # Step 3: 导出
        output_path = await self.inkos.export_book(book_id)

        return NovelResult(
            book_id=book_id,
            output_path=output_path,
            chapter_count=story.output.chapters,
            word_count=story.output.chapters * story.output.words_per_chapter
        )

    async def _run_drama_pipeline(self, story: UnifiedStory) -> DramaResult:
        """运行短剧管线

        流程：
        1. Seedance生成剧本和视频提示词
        """
        logger.info("Running drama pipeline")

        # 使用Seedance生成
        seedance_output = await self.seedance.generate(story.to_dict())

        return DramaResult(
            screenplay=seedance_output.screenplay.to_dict(),
            video_prompts=seedance_output.get_prompts_batch(),
            character_designs=seedance_output.character_designs.to_dict()
        )

    async def _run_hybrid_pipeline(self, story: UnifiedStory) -> HybridResult:
        """运行混合管线

        流程：
        1. 先生成小说
        2. 从小说中提取剧本素材
        3. 生成剧本和视频提示词

        注意：步骤2需要用户确认（Q3决策）
        """
        logger.info("Running hybrid pipeline")

        # Step 1: 生成小说
        novel_result = await self._run_novel_pipeline(story)
        logger.info(f"Novel generated: {novel_result.output_path}")

        # Step 2: 提取剧本素材
        if self.config.extract_for_screenplay:
            logger.info("Extracting screenplay elements from novel")

            # 读取小说内容
            novel_content = await self._read_novel_content(novel_result.output_path)

            # 获取真相文件
            truth_files = await self.inkos.get_truth_files(novel_result.book_id)

            # 提取
            extraction_result = await self.extractor.extract(
                novel_content=novel_content,
                truth_files=truth_files
            )

            # 构建短剧输入
            drama_input = extraction_result.to_unified_story_dict(
                mode='drama',
                target_market=story.target_market.value,
                language=story.language.value,
                genre=story.genre,
                output={
                    'episodes': story.output.episodes,
                    'seconds_per_episode': story.output.seconds_per_episode
                }
            )

            # 如果需要用户确认（Q3决策）
            if not self.config.auto_confirm_extract:
                # 返回中间结果，让用户确认
                # 这里我们直接继续，但在实际使用中可以通过回调或事件让用户确认
                logger.info("Extraction complete, proceeding with drama generation")

        else:
            # 不提取，直接使用原始故事数据
            drama_input = story.to_dict()
            drama_input['mode'] = 'drama'

        # Step 3: 生成短剧
        drama_result = await self._run_drama_pipeline(
            UnifiedStory.from_dict(drama_input)
        )

        return HybridResult(
            novel=novel_result,
            drama=drama_result
        )

    async def _read_novel_content(self, output_path: str) -> str:
        """读取小说内容

        Args:
            output_path: 小说文件路径

        Returns:
            小说内容字符串
        """
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read novel content: {e}")
            return ""

    async def close(self):
        """关闭编排器，释放资源"""
        await self.seedance.close()
