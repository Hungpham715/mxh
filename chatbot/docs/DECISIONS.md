# Engineering decisions

## Explicit state machine

- Classification: custom project choice using a widely used state-machine principle.
- Reason: twelve known retrieval actions and five hard-bounded iterations do not justify LangGraph.
- Trade-off: adding a new intent requires a parser route, planner mapping, template, normalizer contract, fake data, and tests.
- Do not use this choice for open-ended tool ecosystems with genuinely dynamic tool discovery.

## Repository boundary

- Classification: industry-standard persistence boundary.
- Reason: the same workflow must run against fake and Neo4j without production mocks or import-time network calls.
- Trade-off: small protocol and factory layer.

## Server-owned citations

- Classification: security/data-integrity control.
- Reason: paper IDs, titles, and URLs come from graph query results; model text cannot create a citation.
- Trade-off: answer wording and citation rendering are separate.

## Local name catalog

- Classification: custom choice for this approximately 7k-node graph.
- Reason: exact/fuzzy linking works without Neo4j full-text/vector indexes. Cache refresh is TTL/manual.
- Trade-off: this approach would need paging/index redesign at much larger graph sizes.

## UI visual direction

The generated design search suggested an academic palette but an unrelated portfolio layout and remote serif
fonts. The product keeps the navy/research-gold palette, uses local fonts, and adopts a chat/evidence/trace layout.
No analytics, remote font, or decorative image is required.

