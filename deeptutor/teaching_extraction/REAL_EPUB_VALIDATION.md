# Real EPUB validation

Validation material: a locally supplied EPUB edition of *Gödel, Escher, Bach*.

The repository does not include the EPUB or substantial source text. The material was used only to validate extraction shape and provenance requirements.

## Chapter-level validation

The first chapter (WU puzzle) exercises the following teaching structures:

- concepts: formal system, symbol string, axiom, theorem, derivation, decision procedure
- principles/claims: formalization requirement, rule directionality, theorem invariants
- examples: the WJU system and concrete derivations
- misconceptions: confusing a legal string with a theorem, reversing one-way rules, treating a meta-variable as a system symbol
- meta-level distinctions: working inside a formal system versus reasoning about the system

## Findings

1. Segment-only provenance is too coarse. Each extracted node and edge should retain a short evidence excerpt in addition to the segment anchor.
2. The relation vocabulary needs `part_of` and `derived_from` to represent system composition and rule/axiom-derived properties without overloading `supports`.
3. Extraction instructions need explicit semantics for every node and relation type to reduce type drift.
4. Long material should prefer section/heading boundaries before generic character-window boundaries.

These findings are implemented in this follow-up branch; no copyrighted EPUB content is committed.
