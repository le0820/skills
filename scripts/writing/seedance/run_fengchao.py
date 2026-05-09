"""《蜂巢》- 基于文言文素材的自动化创作"""

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

# 配置详细的日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from orchestrator import CreativeOrchestrator


async def main():
    orchestrator = CreativeOrchestrator()

    try:
        result = await orchestrator.run_pipeline({
            'title': '蜂巢',
            'premise': (
                '【时代背景】开国百年城镇化大兴，房价持续上涨百年，社会形成"置业为安身之本"的共识。'
                '国家藉土地丰国库，朝野舆论莫不训民：勤学立身，出仕务工，婚娶安家，置业终老。'
                '当此极巅之岁，世间壮男，年齿多在而立不惑之间，世谓国之柱石生民。\n\n'
                '【主角群体画像】此辈生于承平，长于笃信，自幼谨奉教化，苦读求进，躬身劳作，'
                '素无投机之念，无侥幸之心，无骄纵逸乐之行。一生所守，唯世间教予正道：'
                '尽孝奉亲，持家育后，勤勉立身，不负世事。\n\n'
                '【关键事件】及壮年婚娶，恰逢寰宇屋价至峰，举国之言皆曰：迟则愈贵，无屋无家。'
                '于是此辈男子，罄自身半生之蓄，竭三代六家之资，负重三十年长债，裂身入局，购屋安居。'
                '其非为逐利，非为暴富，唯求一生安稳，家人温饱，岁月寻常。\n\n'
                '【转折】未几，世运骤转。人口渐寂，城镇化尽，地产气运尽散，房价颓落，'
                '昔日重金所置，尽成浮产负资。债券如山，分毫不可免；月供如石，一日不可迟。\n\n'
                '【困境】上则高堂垂暮，疾患频生，赡养无休；下则稚子长成，学业耗竭，用度无尽。'
                '职场亦生苛限，三十五岁便为天堑，盛年精力，日日耗于奔命，疲于偿债。'
                '终身无闲暇，无欢愉，无松缓，无自我。\n\n'
                '【结局与主题】庙堂亦知其弊，欲改法度，然大国改制，动辄以十载、二十载为周期。'
                '独惜生民一身，人寿有期，花甲已暮。山河可缓改，唯此人之华年，一去不返。'
                '当其世间法度渐平之日，此辈壮男，早已半生已过，鬓发凝霜，筋骨早衰。\n\n'
                '【核心矛盾】世有至哀：愈循正道，愈尽心力，愈负重债；愈守本分，愈无归途。'
                '系统可以慢慢救赎时代，却无人救赎已经走完半生的人。'
                '他们不曾负道，不曾负世，不曾负家。唯独世事负了他们。'
            ),
            'mode': 'novel',
            'target_market': 'china',
            'language': 'zh',
            'genre': 'urban',
            'output': {
                'chapters': 4,
                'words_per_chapter': 3000
            },
            'characters': [
                {
                    'id': 'char_0',
                    'name': '陈默',
                    'role': 'protagonist',
                    'description': '三十七岁，生于承平年代，恪守正道的普通人。半生积蓄加三代资产购入婚房，却遭遇时代转轨。',
                    'personality': ['沉默寡言', '勤勉本分', '隐忍坚韧', '不善表达'],
                    'arc': '从笃信正道的顺从者，到认清时代真相却无路可走的困兽'
                },
                {
                    'id': 'char_1',
                    'name': '林小满',
                    'role': 'supporting',
                    'description': '陈默的妻子，同样背负房贷压力，在家庭和工作间疲于奔命。',
                    'personality': ['务实', '焦虑', '偶尔歇斯底里'],
                    'arc': '从对未来充满期待到被现实磨平棱角'
                }
            ],
            'conflicts': [
                {
                    'id': 'conf_0',
                    'type': 'internal',
                    'description': '陈默内心对"正道"的信仰与残酷现实之间的撕裂',
                    'characters_involved': ['char_0']
                },
                {
                    'id': 'conf_1',
                    'type': 'external',
                    'description': '房贷重压、职场年龄歧视、父母养老、子女教育的多重挤压',
                    'characters_involved': ['char_0', 'char_1']
                }
            ]
        })

        print(f"\n生成完成！")
        print(f"模式: {result['mode']}")
        print(f"结果: {json.dumps(result['result'], ensure_ascii=False, indent=2)}")

    except Exception as e:
        print(f"生成失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
