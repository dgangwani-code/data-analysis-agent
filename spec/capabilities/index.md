# Capabilities Index

---

## What Is a Capability?

A capability is a single, discrete action or behavior the agent performs.

## Capabilities in This Project

| Capability | File | Phase |
|-----------|------|-------|
| Dataset Ingestion & Profiling | [dataset-ingestion-and-profiling.md](dataset-ingestion-and-profiling.md) | 1 (single-file) → 2 (multi-file/folder/PDF-OCR) |
| Iterative Question Answering | [iterative-question-answering.md](iterative-question-answering.md) | 1 (core loop) → 2 (charts + cost estimate) |
| Chat Session Persistence | [chat-session-persistence.md](chat-session-persistence.md) | 1 (within-session memory) → 2 (cross-session history browsing) |
| Result Export | [result-export.md](result-export.md) | 2 (Phase 1 ships a labelled, disabled stub only) |

## How to Add a New Capability

Run `/zero-shot-build [description]` on the existing spec. The spec-writer sub-agent will:
1. Create a new file in this directory (`<name>.md`, no number prefix)
2. Update this index
3. Flag any dependencies on existing capabilities
4. Self-review that it fits the architecture and data model before returning

## Capability File Template

Each capability file should answer:
- **What it does** (one sentence)
- **Inputs** (what data it receives)
- **Outputs** (what it produces)
- **External calls** (APIs, LLMs, databases it touches)
- **Business rules**
- **Success criteria** (how we test it)
