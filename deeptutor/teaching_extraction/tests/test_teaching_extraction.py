import json

import pytest

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.teaching_core.models import TeachingNodeType, TeachingRelationType
from deeptutor.teaching_extraction import TeachingExtractionError, TeachingKnowledgeExtractor
from deeptutor.teaching_extraction.normalizer import normalize_batches
from deeptutor.teaching_extraction.schemas import (
    ExtractedEdge,
    ExtractedNode,
    ExtractionBatch,
    SourceAnchor,
)
from deeptutor.teaching_extraction.source_anchor import segment_parsed_document


@pytest.mark.asyncio
async def test_extracts_model_with_source_anchors_and_evidence():
    async def fake_complete(*, prompt: str, system_prompt: str) -> str:
        segment_id = prompt.split("segment_id: ", 1)[1].splitlines()[0]
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "n1",
                        "title": "Formal system",
                        "type": "concept",
                        "content": "A rule-governed symbolic system.",
                        "source_segment_ids": [segment_id],
                        "evidence_quote": "Formal systems provide notation.",
                        "confidence": 0.96,
                    },
                    {
                        "id": "n2",
                        "title": "Self-reference",
                        "type": "concept",
                        "content": "A structure referring to itself.",
                        "source_segment_ids": [segment_id],
                        "evidence_quote": "Self-reference builds on that notation.",
                        "confidence": 0.91,
                    },
                ],
                "edges": [
                    {
                        "source": "n1",
                        "target": "n2",
                        "relation": "prerequisite_of",
                        "source_segment_ids": [segment_id],
                        "evidence_quote": "Self-reference builds on that notation.",
                        "confidence": 0.8,
                    }
                ],
            }
        )

    parsed = ParsedDocument(
        markdown=(
            "# Chapter\n\nFormal systems provide notation. Self-reference builds on that notation."
        ),
        source_hash="abc",
        engine="pymupdf4llm",
    )
    result = await TeachingKnowledgeExtractor(complete_fn=fake_complete).extract(
        parsed,
        source_id="sample.epub",
    )

    assert result.node_count == 2
    assert result.edge_count == 1
    assert result.model.edges[0].relation == TeachingRelationType.PREREQUISITE_OF
    assert all(node.source_refs[0].startswith("sample.epub#") for node in result.model.nodes)
    assert result.model.nodes[0].metadata["source_anchors"]
    assert result.model.nodes[0].metadata["evidence_quotes"]
    assert result.model.edges[0].metadata["evidence_quotes"]


def test_markdown_segmentation_preserves_locator():
    parsed = ParsedDocument(
        markdown="A" * 1400 + "\n\n" + "B" * 1400,
        source_hash="hash",
    )
    segments = segment_parsed_document(
        parsed,
        source_id="book.epub",
        max_chars=1600,
    )
    assert len(segments) == 2
    assert segments[0].anchor.locator.startswith("chars:")
    assert segments[0].anchor.segment_id != segments[1].anchor.segment_id


def test_markdown_segmentation_prefers_heading_boundary():
    markdown = "# Chapter One\n\n" + "A" * 900 + "\n\n# Chapter Two\n\n" + "B" * 900
    parsed = ParsedDocument(markdown=markdown, source_hash="hash")
    segments = segment_parsed_document(
        parsed,
        source_id="book.epub",
        max_chars=1600,
    )
    assert len(segments) == 2
    assert "Chapter Two" not in segments[0].text
    assert segments[1].text.startswith("# Chapter Two")
    assert [segment.anchor.heading for segment in segments] == [
        "Chapter One",
        "Chapter Two",
    ]


@pytest.mark.asyncio
async def test_rejects_hallucinated_source_anchor():
    async def fake_complete(*, prompt: str, system_prompt: str) -> str:
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "n1",
                        "title": "Invented",
                        "type": "concept",
                        "source_segment_ids": ["seg_not_real"],
                        "evidence_quote": "Grounded text",
                        "confidence": 1.0,
                    }
                ],
                "edges": [],
            }
        )

    with pytest.raises(TeachingExtractionError, match="unknown source segments"):
        await TeachingKnowledgeExtractor(complete_fn=fake_complete).extract(
            ParsedDocument(markdown="Grounded text", source_hash="x"),
            source_id="sample.epub",
        )


@pytest.mark.asyncio
async def test_rejects_hallucinated_evidence_quote():
    async def fake_complete(*, prompt: str, system_prompt: str) -> str:
        segment_id = prompt.split("segment_id: ", 1)[1].splitlines()[0]
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "n1",
                        "title": "Invented",
                        "type": "concept",
                        "source_segment_ids": [segment_id],
                        "evidence_quote": "This sentence is not in the source.",
                        "confidence": 1.0,
                    }
                ],
                "edges": [],
            }
        )

    with pytest.raises(TeachingExtractionError, match="evidence_quote is not grounded"):
        await TeachingKnowledgeExtractor(complete_fn=fake_complete).extract(
            ParsedDocument(markdown="Grounded text only.", source_hash="x"),
            source_id="sample.epub",
        )


@pytest.mark.asyncio
async def test_accepts_evidence_quotes_spanning_markdown_artifacts():
    """Quotes copied from blockquotes / lists / bold lines must validate once
    Markdown structural markers are stripped (CJK whitespace-insensitive)."""
    markdown = (
        "# Chapter\n\n"
        "种草的本质，是把这种模糊感受转化为：\n\n"
        "> 原来我真正想要的是这个。\n\n"
        "真正有效的种草必须建立在三个条件上：\n"
        "- 产品确实解决问题；\n"
        "- 内容真实呈现体验；\n\n"
        "**以人为本，观察尚未被表达的真实需求。**"
    )

    async def fake_complete(*, prompt: str, system_prompt: str) -> str:
        segment_id = prompt.split("segment_id: ", 1)[1].splitlines()[0]
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "n1",
                        "title": "Blockquote quote",
                        "type": "concept",
                        "source_segment_ids": [segment_id],
                        "evidence_quote": "种草的本质，是把这种模糊感受转化为：原来我真正想要的是这个。",
                        "confidence": 0.9,
                    },
                    {
                        "id": "n2",
                        "title": "List quote",
                        "type": "concept",
                        "source_segment_ids": [segment_id],
                        "evidence_quote": "产品确实解决问题；内容真实呈现体验；",
                        "confidence": 0.9,
                    },
                    {
                        "id": "n3",
                        "title": "Bold quote",
                        "type": "concept",
                        "source_segment_ids": [segment_id],
                        "evidence_quote": "以人为本，观察尚未被表达的真实需求。",
                        "confidence": 0.9,
                    },
                ],
                "edges": [],
            }
        )

    result = await TeachingKnowledgeExtractor(complete_fn=fake_complete).extract(
        ParsedDocument(markdown=markdown, source_hash="x"),
        source_id="sample.md",
    )
    assert result.node_count == 3
    assert {node.title for node in result.model.nodes} == {
        "Blockquote quote",
        "List quote",
        "Bold quote",
    }


@pytest.mark.asyncio
async def test_grounds_heading_quote_with_appended_period():
    """A quote that is actually a section heading plus a terminal period the
    LLM appended must validate: ATX-heading markers are stripped and cosmetic
    trailing punctuation is tolerated (CJK compact matching)."""
    markdown = (
        "# 《种草》：道层面的经验哲学\n\n"
        "## 2. 需求不是被制造出来的，而是被看见、唤醒和表达出来的\n\n"
        "很多需求原本处于模糊、潜在状态。"
    )

    async def fake_complete(*, prompt: str, system_prompt: str) -> str:
        segment_id = prompt.split("segment_id: ", 1)[1].splitlines()[0]
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "n1",
                        "title": "需求是被看见而非制造的",
                        "type": "concept",
                        "source_segment_ids": [segment_id],
                        "evidence_quote": "需求不是被制造出来的，而是被看见、唤醒和表达出来的。",
                        "confidence": 0.9,
                    }
                ],
                "edges": [],
            }
        )

    result = await TeachingKnowledgeExtractor(complete_fn=fake_complete).extract(
        ParsedDocument(markdown=markdown, source_hash="x"),
        source_id="sample.md",
    )
    assert result.node_count == 1
    node = result.model.nodes[0]
    # the stored quote is snapped back to the verbatim source span (no period)
    assert node.metadata["evidence_quotes"] == [
        "需求不是被制造出来的，而是被看见、唤醒和表达出来的"
    ]


@pytest.mark.asyncio
async def test_grounds_quote_with_minor_llm_drift():
    """Small LLM drift (dropped particle / swapped conjunction) is snapped to
    the closest verbatim source span instead of rejecting the whole batch."""
    markdown = (
        "# 章\n\n"
        "真正有效的种草必须建立在三个条件上：产品确实解决问题，"
        "内容真实呈现体验，企业与用户利益基本一致。"
    )

    async def fake_complete(*, prompt: str, system_prompt: str) -> str:
        segment_id = prompt.split("segment_id: ", 1)[1].splitlines()[0]
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "n1",
                        "title": "种草三个条件",
                        "type": "principle",
                        "source_segment_ids": [segment_id],
                        "evidence_quote": "种草必须建立：产品解决问题，内容呈现真实体验，利益一致",
                        "confidence": 0.9,
                    }
                ],
                "edges": [],
            }
        )

    result = await TeachingKnowledgeExtractor(complete_fn=fake_complete).extract(
        ParsedDocument(markdown=markdown, source_hash="x"),
        source_id="sample.md",
    )
    assert result.node_count == 1
    quote = result.model.nodes[0].metadata["evidence_quotes"][0]
    # grounded span is verbatim from the source (all its characters appear there)
    source_compact = markdown.replace("\n", "").replace(" ", "")
    assert all(char in source_compact for char in quote)


def test_normalizer_merges_duplicate_nodes():
    anchor1 = SourceAnchor(source_id="book", segment_id="s1", locator="chars:0-10")
    anchor2 = SourceAnchor(source_id="book", segment_id="s2", locator="chars:11-20")
    batches = [
        ExtractionBatch(
            nodes=[
                ExtractedNode(
                    id="n1",
                    title="Self Reference",
                    type=TeachingNodeType.CONCEPT,
                    content="short",
                    source_segment_ids=["s1"],
                    evidence_quote="first evidence",
                    confidence=0.7,
                )
            ]
        ),
        ExtractionBatch(
            nodes=[
                ExtractedNode(
                    id="n1",
                    title=" self   reference ",
                    type=TeachingNodeType.CONCEPT,
                    content="a longer explanation",
                    source_segment_ids=["s2"],
                    evidence_quote="second evidence",
                    confidence=0.9,
                )
            ]
        ),
    ]
    model = normalize_batches(
        batches,
        source_id="book",
        anchors={"s1": anchor1, "s2": anchor2},
    )
    assert len(model.nodes) == 1
    assert model.nodes[0].content == "a longer explanation"
    assert len(model.nodes[0].source_refs) == 2
    assert len(model.nodes[0].metadata["evidence_quotes"]) == 2


def test_prerequisite_cycle_is_rejected():
    anchors = {"s1": SourceAnchor(source_id="book", segment_id="s1", locator="x")}
    batch = ExtractionBatch(
        nodes=[
            ExtractedNode(
                id="a",
                title="A",
                type=TeachingNodeType.CONCEPT,
                source_segment_ids=["s1"],
                evidence_quote="A",
            ),
            ExtractedNode(
                id="b",
                title="B",
                type=TeachingNodeType.CONCEPT,
                source_segment_ids=["s1"],
                evidence_quote="B",
            ),
        ],
        edges=[
            ExtractedEdge(
                source="a",
                target="b",
                relation=TeachingRelationType.PREREQUISITE_OF,
                source_segment_ids=["s1"],
                evidence_quote="A B",
            ),
            ExtractedEdge(
                source="b",
                target="a",
                relation=TeachingRelationType.PREREQUISITE_OF,
                source_segment_ids=["s1"],
                evidence_quote="B A",
            ),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        normalize_batches([batch], source_id="book", anchors=anchors)
