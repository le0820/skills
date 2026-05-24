"""Unified Story Schema - 数据交换格式定义

本模块定义了InkOS和Seedance两个管线之间的统一数据格式。
所有Agent之间的数据流转都通过此格式进行。
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum
import uuid


class RunMode(Enum):
    """运行模式"""
    NOVEL = "novel"      # 小说模式：只生成小说
    DRAMA = "drama"      # 短剧模式：生成剧本+视频提示词
    HYBRID = "hybrid"    # 混合模式：小说+剧本+视频提示词


class TargetMarket(Enum):
    """目标市场"""
    CHINA = "china"
    WEST = "west"
    INDIA = "india"
    LATAM = "latam"
    GLOBAL = "global"


class Language(Enum):
    """输出语言"""
    ZH = "zh"    # 中文
    EN = "en"    # 英语
    HI = "hi"    # 印地语
    ES = "es"    # 西班牙语
    PT = "pt"    # 葡萄牙语


class SourceType(Enum):
    """输入来源类型（预留扩展）"""
    INSPIRATION = "inspiration"    # 用户灵感输入
    VIDEO = "video"                # 视频输入（未来扩展）
    TEXT = "text"                  # 文本输入（未来扩展）


@dataclass
class Character:
    """角色定义"""
    id: str
    name: str
    role: str                       # protagonist/antagonist/supporting
    description: str                # 角色描述
    personality: List[str]          # 性格标签
    appearance: Optional[str] = None  # 外貌描述（用于视频生成）
    arc: str = ""                   # 人物弧线
    relationships: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Character':
        return cls(**data)


@dataclass
class PlotPoint:
    """剧情点"""
    id: str
    event: str                      # 事件描述
    purpose: str                    # 事件目的
    characters_involved: List[str]  # 涉及角色ID
    emotional_beat: str             # 情绪节拍
    location: Optional[str] = None  # 地点

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlotPoint':
        return cls(**data)


@dataclass
class Conflict:
    """冲突定义"""
    id: str
    type: str                       # internal/external/relationship/societal
    description: str                # 冲突描述
    characters_involved: List[str]  # 涉及角色ID
    resolution: Optional[str] = None  # 解决方式

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Conflict':
        return cls(**data)


@dataclass
class OutputConfig:
    """输出配置"""
    chapters: int = 10              # 小说章节数
    words_per_chapter: int = 3000   # 每章字数
    episodes: int = 5               # 短剧集数
    seconds_per_episode: int = 60   # 每集时长（秒）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OutputConfig':
        return cls(**data)


@dataclass
class UnifiedStory:
    """统一故事格式 - 两个管线的核心数据交换格式

    Attributes:
        id: 故事唯一标识
        title: 故事标题
        mode: 运行模式（novel/drama/hybrid）
        target_market: 目标市场
        language: 输出语言
        premise: 一句话前提
        logline: 一句话故事线
        genre: 题材类型（对应InkOS的genre）
        themes: 主题列表
        characters: 角色列表
        plot_points: 剧情点列表
        conflicts: 冲突列表
        output: 输出配置
        source_type: 输入来源类型（预留扩展）
        metadata: 额外元数据
    """
    id: str
    title: str
    mode: RunMode
    target_market: TargetMarket
    language: Language
    premise: str
    logline: str = ""
    genre: str = "other"
    themes: List[str] = field(default_factory=list)
    characters: List[Character] = field(default_factory=list)
    plot_points: List[PlotPoint] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    output: OutputConfig = field(default_factory=OutputConfig)
    source_type: SourceType = SourceType.INSPIRATION
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        data = asdict(self)
        # 将枚举转换为字符串值
        data['mode'] = self.mode.value
        data['target_market'] = self.target_market.value
        data['language'] = self.language.value
        data['source_type'] = self.source_type.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UnifiedStory':
        """从字典创建实例

        Raises:
            ValueError: 缺少必填字段或字段格式错误
        """
        # 验证必填字段
        required_fields = ['id', 'title', 'mode', 'target_market', 'language', 'premise']
        for field_name in required_fields:
            if field_name not in data:
                raise ValueError(f"Missing required field: {field_name}")

        # 转换枚举类型
        try:
            mode = RunMode(data['mode'])
            target_market = TargetMarket(data['target_market'])
            language = Language(data['language'])
        except ValueError as e:
            raise ValueError(f"Invalid enum value: {e}")

        # 解析嵌套对象
        characters = [Character.from_dict(c) for c in data.get('characters', [])]
        plot_points = [PlotPoint.from_dict(p) for p in data.get('plot_points', [])]
        conflicts = [Conflict.from_dict(c) for c in data.get('conflicts', [])]
        output = OutputConfig.from_dict(data.get('output', {}))

        # 解析source_type（预留字段）
        source_type = SourceType.INSPIRATION
        if 'source_type' in data:
            try:
                source_type = SourceType(data['source_type'])
            except ValueError:
                pass  # 默认使用inspiration

        return cls(
            id=data['id'],
            title=data['title'],
            mode=mode,
            target_market=target_market,
            language=language,
            premise=data['premise'],
            logline=data.get('logline', ''),
            genre=data.get('genre', 'other'),
            themes=data.get('themes', []),
            characters=characters,
            plot_points=plot_points,
            conflicts=conflicts,
            output=output,
            source_type=source_type,
            metadata=data.get('metadata', {})
        )

    @classmethod
    def from_premise(cls, title: str, premise: str, mode: str = 'novel',
                     target_market: str = 'china', language: str = 'zh',
                     genre: str = 'other') -> 'UnifiedStory':
        """从简单前提创建故事（简化接口）"""
        return cls(
            id=str(uuid.uuid4()),
            title=title,
            mode=RunMode(mode),
            target_market=TargetMarket(target_market),
            language=Language(language),
            premise=premise,
            genre=genre
        )

    def generate_novel_context(self) -> str:
        """生成用于InkOS的小说写作上下文

        Returns:
            格式化的上下文字符串，用于InkOS的--context参数
        """
        context_parts = [
            f"故事标题：{self.title}",
            f"故事前提：{self.premise}",
        ]

        if self.logline:
            context_parts.append(f"故事线：{self.logline}")

        if self.themes:
            context_parts.append(f"主题：{', '.join(self.themes)}")

        if self.characters:
            context_parts.append("\n主要人物：")
            for char in self.characters:
                context_parts.append(f"- {char.name}（{char.role}）：{char.description}")

        if self.conflicts:
            context_parts.append("\n核心冲突：")
            for conflict in self.conflicts:
                context_parts.append(f"- {conflict.description}")

        if self.plot_points:
            context_parts.append("\n关键剧情点：")
            for pp in self.plot_points[:5]:  # 只取前5个
                context_parts.append(f"- {pp.event}")

        return '\n'.join(context_parts)

    def generate_screenplay_context(self) -> str:
        """生成用于Seedance的剧本创作上下文

        Returns:
            格式化的上下文字符串
        """
        context_parts = [
            f"故事标题：{self.title}",
            f"故事前提：{self.premise}",
            f"目标市场：{self.target_market.value}",
            f"语言：{self.language.value}",
        ]

        if self.logline:
            context_parts.append(f"故事线：{self.logline}")

        if self.characters:
            context_parts.append("\n角色设定：")
            for char in self.characters:
                char_info = f"- {char.name}（{char.role}）：{char.description}"
                if char.appearance:
                    char_info += f"\n  外貌：{char.appearance}"
                context_parts.append(char_info)

        if self.plot_points:
            context_parts.append("\n剧情结构：")
            for pp in self.plot_points:
                context_parts.append(f"- [{pp.location or '待定'}] {pp.event}（情绪：{pp.emotional_beat}）")

        return '\n'.join(context_parts)
