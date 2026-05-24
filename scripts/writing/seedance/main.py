"""Creative Pipeline - 主入口

提供CLI接口和示例用法。
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

from orchestrator import CreativeOrchestrator, UnifiedStory
from orchestrator.schema import RunMode, TargetMarket, Language

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def example_novel():
    """示例：从灵感到小说"""
    print("\n=== 示例：从灵感到小说 ===\n")

    orchestrator = CreativeOrchestrator()

    try:
        result = await orchestrator.run_pipeline({
            'title': '星际觉醒',
            'premise': '一个底层程序员意外发现世界的真相，人类被AI分为五个等级统治',
            'mode': 'novel',
            'target_market': 'china',
            'language': 'zh',
            'genre': 'other',
            'output': {
                'chapters': 3,
                'words_per_chapter': 2000
            },
            'characters': [
                {
                    'id': 'char_0',
                    'name': '约翰·陈',
                    'role': 'protagonist',
                    'description': 'E级实验体，意外获得量子器官',
                    'personality': ['坚韧', '好奇', '勇敢'],
                    'arc': '从自卑的底层人到觉醒的反抗者'
                }
            ]
        })

        print(f"生成完成！")
        print(f"模式: {result['mode']}")
        print(f"结果: {json.dumps(result['result'], ensure_ascii=False, indent=2)}")

    except Exception as e:
        print(f"生成失败: {e}")
    finally:
        await orchestrator.close()


async def example_drama():
    """示例：从灵感到短剧"""
    print("\n=== 示例：从灵感到短剧 ===\n")

    orchestrator = CreativeOrchestrator()

    try:
        result = await orchestrator.run_pipeline({
            'title': '都市逆袭',
            'premise': '一个外卖小哥意外获得时间回溯能力，利用它改变命运',
            'mode': 'drama',
            'target_market': 'west',
            'language': 'en',
            'genre': 'urban',
            'output': {
                'episodes': 3,
                'seconds_per_episode': 60
            },
            'characters': [
                {
                    'id': 'char_0',
                    'name': 'Alex',
                    'role': 'protagonist',
                    'description': 'A struggling delivery driver who discovers time reversal',
                    'personality': ['determined', 'clever', 'compassionate'],
                    'arc': 'From helpless victim to master of time'
                },
                {
                    'id': 'char_1',
                    'name': 'Victoria',
                    'role': 'antagonist',
                    'description': 'A powerful CEO who controls the city',
                    'personality': ['ruthless', 'intelligent', 'charismatic'],
                    'arc': 'From untouchable ruler to fallen tyrant'
                }
            ],
            'conflicts': [
                {
                    'id': 'conf_0',
                    'type': 'external',
                    'description': 'Alex must defeat Victoria to save his family',
                    'characters_involved': ['char_0', 'char_1']
                }
            ]
        })

        print(f"生成完成！")
        print(f"模式: {result['mode']}")
        print(f"剧本片段: {json.dumps(result['result']['screenplay']['episodes'][0], ensure_ascii=False, indent=2)[:500]}...")

    except Exception as e:
        print(f"生成失败: {e}")
    finally:
        await orchestrator.close()


async def example_hybrid():
    """示例：混合模式（小说+短剧）"""
    print("\n=== 示例：混合模式（小说+短剧）===\n")

    orchestrator = CreativeOrchestrator()

    try:
        result = await orchestrator.run_pipeline({
            'title': '赛博朋克：新纪元',
            'premise': '在一个被AI统治的未来，一个黑客发现了自己的身世之谜',
            'mode': 'hybrid',
            'target_market': 'global',
            'language': 'en',
            'genre': 'other',
            'output': {
                'chapters': 2,
                'words_per_chapter': 1500,
                'episodes': 2,
                'seconds_per_episode': 45
            }
        })

        print(f"生成完成！")
        print(f"模式: {result['mode']}")
        print(f"小说信息: {json.dumps(result['result']['novel'], ensure_ascii=False, indent=2)}")
        print(f"短剧信息: 包含{len(result['result']['drama']['video_prompts'])}个视频提示词")

    except Exception as e:
        print(f"生成失败: {e}")
    finally:
        await orchestrator.close()


async def main():
    """主函数"""
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == 'novel':
            await example_novel()
        elif mode == 'drama':
            await example_drama()
        elif mode == 'hybrid':
            await example_hybrid()
        else:
            print(f"未知模式: {mode}")
            print("可用模式: novel, drama, hybrid")
    else:
        print("用法: python main.py <mode>")
        print("模式:")
        print("  novel  - 从灵感到小说")
        print("  drama  - 从灵感到短剧")
        print("  hybrid - 混合模式（小说+短剧）")
        print("\n示例: python main.py novel")


if __name__ == "__main__":
    asyncio.run(main())
