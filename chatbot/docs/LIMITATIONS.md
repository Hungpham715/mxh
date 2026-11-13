# Limitations

- The product can answer only facts represented by the scoped graph. It does not search the web, PDFs, abstracts, or a vector store.
- The snapshot covers sampled NLP papers from 2023–2025. It is not a complete scholarly index.
- Only 26 internal-corpus `CITES` edges exist in the recorded snapshot; absence is not global non-citation.
- Topic rules are precision-first and most papers lack a topic edge. Missing `HAS_TOPIC` is not proof of non-membership.
- `AFFILIATED_WITH` is evidence on specific papers, not a current employer. Coauthor affiliation uses paper-ID intersection.
- Follow-up pronoun/reference resolution is not promised. Send explicit names or IDs when a reference is ambiguous.
- Fake mode is deterministic plumbing evidence only. It is never a model benchmark or live database result.
- Live Aura, Ollama, local adapter inference, and training require external resources and are reported `NOT RUN` when absent.

