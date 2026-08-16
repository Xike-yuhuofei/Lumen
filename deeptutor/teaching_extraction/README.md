# Teaching Knowledge Extraction

`teaching_extraction` converts the canonical document parse IR into the
`TeachingKnowledgeModel` consumed by `teaching_core`.

```text
PDF / EPUB / Markdown / Office
        |
        v
ParseService -> ParsedDocument
        |
        v
TeachingKnowledgeExtractor
        |
        +-- source segmentation + SourceAnchor
        +-- schema-constrained LLM extraction
        +-- normalization / deduplication
        +-- prerequisite DAG validation
        |
        v
TeachingKnowledgeModel
        |
        v
TeachingKnowledgeGraph -> TeachingEngine
```

## Boundaries

- Parsing owns file-format handling.
- Extraction owns pedagogical structure discovery.
- Teaching Core owns the domain schema and deterministic teaching decisions.
- RAG/Neo4j/LlamaIndex are not dependencies of this module.
- LLM output is treated as untrusted input: Pydantic schema validation, source
  anchor validation and prerequisite-cycle validation all run before a model is
  accepted.

## EPUB

The existing `pymupdf4llm` parser supports `.epub`, so an EPUB can flow through
the canonical parse layer without an EPUB-specific teaching implementation:

```python
from deeptutor.services.parsing.service import ParseService
from deeptutor.teaching_extraction import TeachingKnowledgeExtractor

parsed = ParseService().parse("book.epub", engine="pymupdf4llm")
result = await TeachingKnowledgeExtractor().extract(
    parsed,
    source_id="book.epub",
)
teaching_model = result.model
```

Install the optional parser extra when needed:

```bash
pip install -e '.[parse-pymupdf4llm]'
```

## V1 limitation

V1 extracts relations supported inside each source segment and then merges
duplicate nodes deterministically. Book-global relation reconciliation across
distant chapters is intentionally deferred to a later synthesis pass. This keeps
the first implementation inspectable and testable before adding global graph
inference.
