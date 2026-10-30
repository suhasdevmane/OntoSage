# OntoSage+: Designing and Evaluating Human–Smart Building Conversation with Incomplete Data, from Stakeholders' Questions to Decisions

Supplementary material for review (anonymised).

| Folder | What it holds | In the article |
|---|---|---|
| `01_Appendices/` | Appendices A–H, as printed on pages 46–72 of the submitted article | Appendices A–H |
| `02_Task_bank_and_keys/` | The 12 study forms (S1-1 … S4-3) and their keys, from the task bank frozen on 14 October 2026 | §5.4, Appendix G |
| `03_Answer_label_rubric/` | The rules used to label every answer, live and offline | §5.5 |
| `04_Codebooks/` | Part A codebook v1 and v2; Part C codebook; Stage 5 codebook; the agreement and adjudication procedure | §5.2, §5.5, Appendices D and E |
| `05_Comparison_assistant/` | Assistant B's prompt, seven tools, settings and code, frozen before the study | §5.3 |
| `06_Analysis_scripts/` | The scripts that produce the article's numbers, tables and figures, their outputs, and the files of values the article prints | §3, §5–§8 |
| `07_Study_materials/` | The study form's pages as participants saw them: background questions, goal pages, decisions and their options, questionnaires | §5.4 |
| `08_Data/` | The survey's anonymised questions, rankings and answers, and the study's de-identified data with both coders' labels | §3, §5–§8 |

The system's code, as frozen for the study: https://anonymous.4open.science/r/OntoSage-45E7/ (an anonymised copy of the repository). The data are in `08_Data/`.

Licence: see `LICENSE.txt`.

## Names and identifiers

- **OntoSage+** is the system studied. Participants used it under the name OntoSage, which the code, file names and participant-facing materials keep.
- **Assistant B** is the comparison assistant of §5.3. The code and the rubric call it "the instructed assistant" or "the baseline". **A-minus** is OntoSage+ with its referent and answer-relevance checks turned off (§5.3).
- **P01–P30** are the study's participants, with the codes the article uses (for example, P04). **C001–C096** are the survey's contributors. The two sets of codes are unrelated.
- **Building A** is the building studied.

## Anonymisation for review

These files were prepared for double-blind review. Where a file named the building, the institution or a person, the name was replaced:

| Original | Replaced by |
|---|---|
| the building's name, and participants' misspellings of it | `Building A` |
| the building's namespace | `http://example.org/buildingA#` |
| the institution's name; the city, street, district, postcode and region | `[university]`, `[city]`, `[street]`, `[district]`, `[postcode]`, `[region]` |
| the names of the schools the building houses | `[school]` |
| the institution's web domains | `[university domain]` |
| the ethics approval reference | `[anonymised]` |
| the authors' names in comments, notes and documents | `the first author`, `the second author`, `the third author` |
| other people's names that a participant typed | `[name]` |
| the chat interface's name for the assistant | `[anonymised]` (`[assistant]` where a participant used it) |
| the study server's domain | `example.org` |
| the model gateway's address | `[gateway]` |
| telephone numbers in the building's records | `[phone]` |
| chart file names that carried a session's date and time | `viz_[removed]` |

The survey contributors' IDs were also recoded from P01–P96, as in the authors' working files, to C001–C096 in the same order, so that they cannot be confused with the study participants' codes.

Apart from these replacements and the omissions each folder's README lists, no file was changed: no number, label, code or answer. Each folder's README names the files it changed.
