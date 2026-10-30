# Study materials

Supports §5.4 (Participants; Tasks). Each session ran through a study form, a small web application, beside OntoSage+'s chat interface; participants asked OntoSage+ in the chat interface and recorded their decisions in the form.

| File | What it holds |
|---|---|
| `study_form_pages.pdf` | Every page of the study form after consent, with the wording, answer options and scales participants saw. It is generated from the form application's own page definitions, the code that ran the sessions. |
| `task_orders.csv` | The six form versions, V1–V6: three balanced lists of six tasks, each in a forward and a reverse order. Each participant did one version (§5.4). |

`study_form_pages.pdf` holds, in order: the background questions; the participant's own questions, written before using OntoSage+; how the tasks work, with a practice question; for each of the twelve study forms, its goal page and its decision page (the decision, confidence, whether the participant would act without checking further, helpfulness, whether they opened the evidence panel, and the reason); the attention check shown after the third task; the own questions asked live; the System Usability Scale; the three trust items and the mental-effort item; and the three closing questions. A participant saw six of the twelve forms, in the order of their version.

At start, the form application compared the task bank with the SHA-256 recorded at the freeze (`02_Task_bank_and_keys`) and refused to start if they differed. The goal pages, decisions and options therefore come from the frozen bank.

Left out: the information sheet, the consent form and the debrief, which name the institution and the researchers, and the form application itself, which also handled the consent records and participants' personal access links.

**Edits for anonymity:** the building's name became "Building A" (3 places). "OntoSage" is kept: participants used OntoSage+ under that name.
