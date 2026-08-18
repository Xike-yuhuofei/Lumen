"""The fixed Learn Benchmark Set — real materials, faithfully mapped.

Each entry is a real material already in the repo, designed into modules and
knowledge points *the way the tutor would design them after reading it*, with
``description`` and ``source_ref`` taken verbatim / structurally from the
source text and ``misconceptions`` taken from the misconceptions the material
itself discusses (never invented for the benchmark).

Material diversity (per the goal):

* ``zhongcao``   — 概念密集型, short (67-line essay), every section is a
                   conceptual claim.
* ``textile``    — 长篇材料 (56k lines, 70 chapters, 9 parts) with explicit
                   hierarchy and prerequisites (认知基础 -> 纤维 -> 纱线 ->
                   织物结构 -> 性能 -> 应用). A focused subset is mapped to
                   keep the loop faithful yet tractable.

Every KP carries an ``answer`` (the canonical correct response the harness
uses as the expected answer of a posed question) so the deterministic harness
can grade without an LLM. ``misconceptions`` hold ``{statement, correction}``
taken from the material's own "常见误区" sections where available.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "BenchmarkKP",
    "BenchmarkModule",
    "BenchmarkMaterial",
    "BENCHMARK_SET",
]

# Canonical source identifiers used in ``source_ref`` locators.
ZHONGCAO_SRC = "种草-道层面的经验哲学"
TEXTILE_SRC = "纺织面料系统学"


@dataclass(frozen=True)
class BenchmarkKP:
    """One benchmark knowledge point (mirrors mastery_build's shape).

    ``id`` is filled in by the harness with the actual generated id for the
    run's path (``{path_id}_m{m}_kp{j}``); the static definitions leave it
    empty because ids are path-scoped.
    """

    name: str
    type: str  # memory | concept | procedure | design
    description: str
    source_ref: str
    answer: str = ""
    misconceptions: list[dict] = field(default_factory=list)
    id: str = ""


@dataclass(frozen=True)
class BenchmarkModule:
    name: str
    knowledge_points: list[BenchmarkKP] = field(default_factory=list)


@dataclass(frozen=True)
class BenchmarkMaterial:
    id: str
    title: str
    source_path: str
    modules: list[BenchmarkModule]

    def as_build_payload(self) -> list[dict]:
        """The ``modules`` argument for ``mastery_build``."""
        return [
            {
                "name": module.name,
                "knowledge_points": [
                    {
                        "name": kp.name,
                        "type": kp.type,
                        "description": kp.description,
                        "source_ref": kp.source_ref,
                        "misconceptions": list(kp.misconceptions),
                    }
                    for kp in module.knowledge_points
                ],
            }
            for module in self.modules
        ]

    def kp_ids(self) -> list[str]:
        """Deterministic kp ids in build order (mirrors _parse_modules)."""
        return [f"{self.id}_m{m}_kp{j}" for m, mod in enumerate(self.modules) for j in range(len(mod.knowledge_points))]

    def kp_index(self) -> dict[str, int]:
        return {kp_id: i for i, kp_id in enumerate(self.kp_ids())}


# ── 1. 《种草》·"道"层面的经验哲学（概念密集型）─────────────────────────

_ZHONGCAO_MIS = [
    {
        "statement": "种草就是说服用户购买",
        "correction": "种草是帮助用户发现并实现其向往的生活，而非说服购买",
    },
    {
        "statement": "真诚只是一种传播风格",
        "correction": "真诚是经营逻辑：产品、内容与实际体验不一致只是透支信任",
    },
]

ZHONGCAO: BenchmarkMaterial = BenchmarkMaterial(
    id="zhongcao",
    title="《种草》：“道”层面的经验哲学",
    source_path="data/knowledge_bases/种草/raw/种草-道层面的经验哲学.md",
    modules=[
        BenchmarkModule(
            name="种草的道",
            knowledge_points=[
                BenchmarkKP(
                    name="种草的核心命题",
                    type="concept",
                    description="种草不是说服用户购买，而是帮助用户发现并实现其向往的生活",
                    source_ref=f"{ZHONGCAO_SRC}#核心命题",
                    answer="帮助用户发现并实现其向往的生活",
                    misconceptions=_ZHONGCAO_MIS[:1],
                ),
                BenchmarkKP(
                    name="从卖产品转向理解人",
                    type="concept",
                    description="用户购买的往往不是产品本身，而是产品所代表的某种生活状态",
                    source_ref=f"{ZHONGCAO_SRC}#1",
                    answer="产品代表的生活状态",
                ),
                BenchmarkKP(
                    name="需求是被看见、唤醒而非制造",
                    type="concept",
                    description="需求不是被制造出来的，而是被看见、唤醒和表达出来的",
                    source_ref=f"{ZHONGCAO_SRC}#2",
                    answer="需求是被看见、唤醒和表达出来的",
                ),
                BenchmarkKP(
                    name="情绪是商业机会的早期信号",
                    type="concept",
                    description="人的异常情绪可能预示尚未形成规模的趋势，数据只能证明已发生的趋势",
                    source_ref=f"{ZHONGCAO_SRC}#3",
                    answer="人的异常情绪可能预示尚未形成规模的趋势",
                ),
                BenchmarkKP(
                    name="真诚的三个条件",
                    type="memory",
                    description="产品确实解决问题；内容真实呈现体验；企业与用户利益基本一致",
                    source_ref=f"{ZHONGCAO_SRC}#4",
                    answer="产品确实解决问题；内容真实呈现体验；企业与用户利益基本一致",
                    misconceptions=_ZHONGCAO_MIS[1:],
                ),
                BenchmarkKP(
                    name="用户是价值共同创造者",
                    type="concept",
                    description="用户会参与需求表达、产品改进、内容生产和口碑传播，形成理解-创造-反馈-改进-分享的循环",
                    source_ref=f"{ZHONGCAO_SRC}#5",
                    answer="用户参与需求表达、产品改进、内容生产和口碑传播",
                ),
                BenchmarkKP(
                    name="种草是组织能力",
                    type="design",
                    description="种草要求产品、研发、供应链、服务和营销围绕同一用户体验协同，评价标准从单次交易扩展到长期价值",
                    source_ref=f"{ZHONGCAO_SRC}#6",
                    answer="围绕同一用户体验协同，把评价标准扩展到长期价值",
                ),
                BenchmarkKP(
                    name="以人为本的种草逻辑",
                    type="design",
                    description="以人为本，观察尚未被表达的真实需求，用产品和体验帮助用户接近向往的生活，并通过长期信任形成自然传播",
                    source_ref=f"{ZHONGCAO_SRC}#一句话总结",
                    answer="以人为本，观察尚未被表达的需求，用产品和体验帮助用户接近向往的生活，以长期信任形成自然传播",
                ),
            ],
        )
    ],
)


# ── 2. 《纺织面料系统学》· 从认知基础到内衣应用的层级链路（长篇/层级）───

_TEXTILE_MIS = {
    "fabric_system": {
        "statement": "面料就是一块布或某种成分",
        "correction": "面料不是单一材料，而是由纤维、纱线、织物结构和染整工艺共同形成的系统结果",
    },
    "name_judges": {
        "statement": "看到面料名称就能直接判断面料好坏",
        "correction": "必须追问纤维、纱线、组织结构、后整理、检测指标与适用场景，名称不能决定好坏",
    },
    "elastic": {
        "statement": "氨纶含量越高弹力越好",
        "correction": "弹力取决于氨纶形态（裸氨/包芯纱/包覆纱）、纤维弹性回复与织物结构共同作用",
    },
}

TEXTILE: BenchmarkMaterial = BenchmarkMaterial(
    id="textile",
    title="纺织面料系统学（第1/5/12/19/26/32/51章 映射）",
    source_path="data/knowledge_bases/纺织面料系统学/raw/纺织面料系统学.md",
    modules=[
        BenchmarkModule(
            name="第一篇·面料认知基础",
            knowledge_points=[
                BenchmarkKP(
                    name="面料是多层系统",
                    type="concept",
                    description="面料由纤维、纱线、组织结构和染整工艺共同形成的材料系统，成分只能说明一部分",
                    source_ref=f"{TEXTILE_SRC}#第01章",
                    answer="纤维、纱线、织物结构和染整工艺共同形成",
                    misconceptions=[_TEXTILE_MIS["fabric_system"]],
                ),
                BenchmarkKP(
                    name="面料、纤维、纱线、织物的区别",
                    type="memory",
                    description="纤维是最小纺织单元；纱线是线状材料；织物是片状结构；面料是经染色、整理、检验后可用于产品开发的织物",
                    source_ref=f"{TEXTILE_SRC}#第01章",
                    answer="纤维是单元、纱线是线状、织物是结构、面料是可用成品",
                ),
                BenchmarkKP(
                    name="面料名称不能决定好坏",
                    type="concept",
                    description="消费化名称（冰丝、德绒、牛奶丝）需验证；必须追问纤维、纱线、组织、后整理、检测与场景",
                    source_ref=f"{TEXTILE_SRC}#第01章",
                    answer="名称只说明来源/结构/工艺/场景之一，必须追问六个维度",
                    misconceptions=[_TEXTILE_MIS["name_judges"]],
                ),
            ],
        ),
        BenchmarkModule(
            name="第二篇·纤维系统",
            knowledge_points=[
                BenchmarkKP(
                    name="纤维在面料系统中的作用",
                    type="concept",
                    description="纤维是面料的物质基础；天然/再生/合成纤维在性能与成本上差异显著",
                    source_ref=f"{TEXTILE_SRC}#第05章",
                    answer="纤维是面料的物质基础，决定性能与成本",
                ),
                BenchmarkKP(
                    name="纤维选择从产品场景倒推",
                    type="design",
                    description="从产品需求与使用场景倒推材料组合，而非从名词出发",
                    source_ref=f"{TEXTILE_SRC}#第11章",
                    answer="从产品需求和使用场景倒推材料组合",
                ),
            ],
        ),
        BenchmarkModule(
            name="第三篇·纱线系统",
            knowledge_points=[
                BenchmarkKP(
                    name="纱线细度体系",
                    type="memory",
                    description="支数、旦数、特克斯是不同细度表达，纱线是纤维到织物的桥梁",
                    source_ref=f"{TEXTILE_SRC}#第13章",
                    answer="支数、旦数、特克斯是细度表达",
                ),
                BenchmarkKP(
                    name="弹力纱线的形态决定弹力",
                    type="concept",
                    description="裸氨、包芯纱、包覆纱等形态不同，氨纶含量不是弹力的唯一决定因素",
                    source_ref=f"{TEXTILE_SRC}#第16章",
                    answer="氨纶形态、纤维弹性回复与织物结构共同决定弹力",
                    misconceptions=[_TEXTILE_MIS["elastic"]],
                ),
            ],
        ),
        BenchmarkModule(
            name="第四篇·织物结构系统",
            knowledge_points=[
                BenchmarkKP(
                    name="针织、梭织与非织造的基本差异",
                    type="concept",
                    description="三者在成形方式、弹性、尺寸稳定性与用途上差异显著",
                    source_ref=f"{TEXTILE_SRC}#第20章",
                    answer="成形方式不同导致弹性与稳定性不同",
                ),
                BenchmarkKP(
                    name="梭织结构：平纹、斜纹、缎纹",
                    type="memory",
                    description="三种基本组织在紧度、光泽、手感与用途上不同",
                    source_ref=f"{TEXTILE_SRC}#第21章",
                    answer="平纹紧实、斜纹立体、缎纹光滑",
                ),
            ],
        ),
        BenchmarkModule(
            name="第五篇·性能与应用",
            knowledge_points=[
                BenchmarkKP(
                    name="舒适性能与面料选择",
                    type="concept",
                    description="柔软、亲肤、透气、吸湿、速干等舒适性能由纤维、结构、整理共同决定",
                    source_ref=f"{TEXTILE_SRC}#第26章",
                    answer="舒适性能由纤维、结构与整理共同决定",
                ),
                BenchmarkKP(
                    name="性能权衡：不能既要又要还要",
                    type="design",
                    description="面料必须在舒适、功能、成本、耐久之间取舍，面向产品场景做最优解",
                    source_ref=f"{TEXTILE_SRC}#第32章",
                    answer="面向产品场景在舒适、功能、成本、耐久之间取舍",
                ),
                BenchmarkKP(
                    name="内衣内裤面料的选择逻辑",
                    type="design",
                    description="贴身场景优先亲肤、透气、吸湿、尺寸稳定与安全指标，兼顾耐洗与成本",
                    source_ref=f"{TEXTILE_SRC}#第51章",
                    answer="贴身场景优先亲肤透气吸湿与安全，兼顾耐洗成本",
                ),
            ],
        ),
    ],
)


BENCHMARK_SET: dict[str, BenchmarkMaterial] = {
    ZHONGCAO.id: ZHONGCAO,
    TEXTILE.id: TEXTILE,
}


def get_material(material_id: str) -> BenchmarkMaterial:
    try:
        return BENCHMARK_SET[material_id]
    except KeyError:
        raise KeyError(f"unknown benchmark material: {material_id!r}") from None
