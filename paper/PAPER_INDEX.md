# PAPER_INDEX.md — Section→Line Map for `research paper.tex`

Use this index BEFORE editing `research paper.tex`. Read only the line range you need — never the whole file.

**File:** [research paper.tex](research paper.tex) — 1,224 lines total
**Last updated:** 2026-04-17

## Top-level sections

| Section | Lines | Description |
|---------|-------|-------------|
| Preamble (packages) | 1–87 | acmart, packages, TikZ libs |
| Abstract | 88–94 | Context gap + evaluation summary |
| CCS + keywords | 96–130 | CCSXML block |
| **1 Introduction** | 135–163 | Motivation, 4 RQs, contributions, roadmap |
| **2 Related Work** | 165–207 | 4 subsections inc. Zero-Knowledge definition |
| **3 Phase 1: Understanding Stakeholder Intentions** | 209–595 | Formative study + topic prioritisation (merged) |
| **4 OntoSage** | 597–765 | System architecture + representative use cases |
| **5 Evaluation Deployment** | 767–854 | 3 buildings, 15 participants, protocol |
| **6 Results** | 853–1003 | Quantitative findings by RQ + corpus coverage |
| **7 Discussion** | 1005–1055 | Design principles, error analysis, perceived value |
| **8 Limitations and Future Work** | 1056–1091 | Limitations first, then future directions |
| **9 Conclusion** | 1092–~1101 | Wrap |
| Acknowledgments | ~1106–1107 | Ethics note |
| **App. A** Sample Questions | 1117–1173 | 24 questions × 8 domains from corpus |
| **App. B** System Interactions | 1174–1224 | 4 verbatim Q&A pairs from eval log |
| Bibliography | ~1220–1224 | ACM-Reference-Format |

## Subsection detail

### §2 Related Work (165–207)

| Subsection | Lines |
|------------|-------|
| 2.1 HBI & Data Accessibility | 170–176 |
| 2.2 Conversational AI in the Built Environment | 178–186 |
| 2.3 Cross-Building Heterogeneity & Semantic Standards | 188–194 |
| 2.4 Defining Zero-Knowledge Interaction (**NEW**) | 196–207 |

### §3 Phase 1: Understanding Stakeholder Intentions (209–595)

| Subsection | Lines |
|------------|-------|
| 3.1 Study Design: Staged Prompting | 214–225 |
| 3.2 Participants and Ethics | 226–264 |
| 3.3 Analysis: Taxonomy Development | 265–283 |
| 3.4 Corpus Overview | 284–347 |
| 3.5 Stage Comparison: The Context Gap | 348–441 |
|  — 3.5.1 Quantitative Stage Effects | 351–392 |
|  — 3.5.2 Qualitative Stage Divergence | 393–404 |
|  — 3.5.3 Novelty and Anchoring Effects | 405–416 |
|  — 3.5.4 The "Context Gap" | 417–441 |
| 3.6 Complexity Preference Across Roles | 442–464 |
| 3.7 Implications for System Design | 465–470 |
| 3.8 Aggregate Topic Priorities | 474–488 |
| 3.9 Topic Clustering | 489–493 |
| 3.10 Priority vs. Volume Trade-off | 494–498 |
| 3.11 Role-Based Domain Preferences | 499–541 |
| 3.12 Question Complexity Preferences (RQ3) | 542–565 |
| 3.13 Capability Matrix | 566–595 |

### §4 OntoSage (597–765)

| Subsection | Lines |
|------------|-------|
| 4.1 Design Rationale | 602–605 |
| 4.2 System Architecture | 606–638 |
| 4.3 Query Pipeline | 639–671 |
| 4.4 Intent Classification: Taxonomy to System | 672–685 |
| 4.5 Knowledge Graph and Semantic Grounding | 686–693 |
| 4.6 Safe Analytics | 694–702 |
| 4.7 Cross-Building Adaptation (T0–T3) | 703–714 |
| 4.8 Privacy and Safety | 715–718 |
| 4.9 System Interface | 719–749 |
| 4.10 Representative Use Cases (**NEW**) | 750–765 |

### §5 Evaluation Deployment (767–854)

| Subsection | Lines |
|------------|-------|
| 5.1 Deployment Environments | 772–795 |
| 5.2 Participants | 796–817 |
| 5.3 Task Design | 818–830 |
| 5.4 Evaluation Instruments | 831–840 |
| 5.5 Procedure | 841–854 |

### §6 Results (853–1003)

| Subsection | Lines |
|------------|-------|
| 6.1 Stakeholder Intentions and the Context Gap (RQ1) | 859–869 |
| 6.2 Task Completion and Translation Accuracy (RQ2) | 870–878 |
| 6.3 Usability and Cognitive Load (RQ2) | 879–927 |
| 6.4 Question Types and Role-Based Behaviour (RQ3) | 928–936 |
| 6.5 Cross-Building Adaptation Effort (RQ4) | 937–967 |
| 6.6 Corpus-Level Coverage Analysis (**NEW**) | 968–1003 |

### §7 Discussion (1005–1055)

| Subsection | Lines |
|------------|-------|
| 7.1 Design Principles for Zero-Knowledge Building AI | 1010–1022 |
| 7.2 Error Analysis and Gap Categories | 1023–1037 |
| 7.3 Perceived Value and Adoption | 1038–1055 |

### §8 Limitations and Future Work (1056–1091)

| Subsection | Lines |
|------------|-------|
| 8.1 Limitations | 1059–1071 |
| 8.2 Future Directions | 1072–1091 |

## Quick lookups by task

| Task | Lines |
|------|-------|
| Refresh abstract stats | 88–94 |
| Add a new RQ | 143–148 |
| Add a related work citation | 165–207 |
| Update Zero-Knowledge definition | 196–207 |
| Update Context Gap percentages | 417–441 |
| Update OntoSage component description | 597–765 |
| Update Building A/B/C characteristics table | 772–795 |
| Update adaptation effort table | 937–967 |
| Update participant demographics | 793–815 |
| Update RQ1 finding | 859–869 |
| Update RQ2 finding | 870–927 |
| Update RQ3 finding | 928–936 |
| Update RQ4 finding | 937–967 |
| Update corpus coverage section | 968–1003 |
| Update design principles | 1010–1022 |
| Update error analysis | 1023–1037 |
| Update limitations | 1059–1071 |

## Figures + tables registry

| Label | Type | Lines | Source file |
|-------|------|-------|-------------|
| `fig:role-distribution` | image | ~247–253 | `A2_role_distribution.pdf` |
| `tab:demographics` | table | ~221–243 | inline |
| `tab:corpus-stats` | table | ~279–318 | inline |
| `fig:domain-distribution` | image | ~322–328 | `B4_domain_distribution.pdf` |
| `fig:intent-heatmap` | image | ~330–336 | `B4_intent_heatmap.pdf` |
| `tab:stage-stats` | table | ~345–360 | inline |
| `tab:intent-by-stage` | table | ~366–381 | inline |
| `fig:tfidf-comparison` | image | ~387–393 | `C2_stage_tfidf_comparison.pdf` |
| `fig:novelty` | image | ~399–405 | `C3_novelty_by_stage.pdf` |
| `tab:domain-by-stage` | table | ~412–428 | inline |
| `fig:complexity-by-stage` | image | ~437–443 | `B4_complexity_by_stage.pdf` |
| `fig:complexity-preference` | image | ~447–453 | `F2_complexity_preference.pdf` |
| `fig:borda-scores` | image | ~473–479 | `E1_borda_scores.pdf` |
| `fig:role-domain-heatmap` | image | ~498–504 | `D1_role_domain_heatmap.pdf` |
| `tab:concordance` | table | ~516–534 | inline |
| `tab:question-preferences` | table | ~541–556 | inline |
| `tab:capability-matrix` | table | ~565–583 | inline |
| `fig:architecture` | image | ~615–621 | `fig12_ontosage_system_architecture.pdf` |
| `fig:framework-architecture` | image | ~625–631 | `fig13_framework_architecture_taxonomy.pdf` |
| `alg:ontosage` | algorithm | ~645–664 | inline |
| `fig:ui-examples` | subfigure* | ~717–741 | `ui_example_{1,2,3}.png` |
| `tab:building-characteristics` | table | ~756–774 | inline |
| `tab:participant-demographics` | table | ~780–796 | inline |
| `tab:sus-results` | table | ~887–903 | inline |
| `tab:nasa-tlx` | table | ~907–927 | inline |
| `tab:adaptation-components` | table | ~942–964 | inline |
| `fig:corpus-stage-coverage` | image | ~992–998 | `H5_corpus_stage_coverage.pdf` |
| `fig:domain-complexity-coverage` | image | ~1007–1013 | `H7_domain_complexity_heatmap.pdf` |

## When to refresh this index

- After any edit that adds/removes >20 lines, run:
  ```bash
  grep -nE "^\\\\(section|subsection|subsubsection|begin\\{abstract\\})" "paper/research paper.tex"
  ```
- Update the line numbers above to match
- Update "Last updated" date at top
