# Writing boundaries — IMWUT submission

Applies to `paper/research paper.tex` and anything drafted for it.

The target is ACM IMWUT: rigorous, empirical HCI and ubiquitous computing. Write as an
engineering researcher writes — precise about instruments, procedures, and what the numbers
do and do not show.

---

## 0. The numbers come first, and a prose pass must not touch them

This paper's failure mode has never been prose quality. Over four sessions, nine classes of
defect were found and **every one was numeric**: two chi-square values stale against their
source tables, all 24 cells of one panel stale, four figure counts wrong, a table row
terminator that silently merged cells, invented inter-rater values, fabricated participant
quotes. None was visible on the page; all were found by checking a number against the file
that produced it.

So:

- **A prose or style pass changes words, never digits.** If a sentence reads badly *because*
  of a number, fix the sentence around it and leave the number alone.
- **Every number traces to a generating artefact.** `paper/verify_claims.py` maps each table
  to the file that produced it and reports its own false-match rate. Run it after any edit
  that touches a table.
- **A figure's numbers live in its `.xml`, not only in the exported `.pdf`.** Correcting the
  paper without correcting `figures/*.xml` means the next re-export reverts it.
- **Do not "improve" a hedge into a claim.** "should be read as an upper bound", "we have not
  re-measured", "the audit does not verify correctness" are load-bearing. They are what makes
  the rest credible.

## 1. Words and constructions to avoid

**Do not use:** *delve, leverage* (as a verb), *showcase, testament, tapestry, navigate* (as a
metaphor), *beacon, holistic, bespoke, paramount, revolutionise, furthermore, seamless,
cutting-edge, game-changing, unlock, harness, realm, landscape* (as a metaphor), *underscore,
pivotal, crucial* (unless the criticality is demonstrated).

**Use with care, not banned:**

- **robust** — correct and precise in its technical sense (*robust to sensor drift*, *a
  robustness check*). Do not use it as a synonym for *good* or *strong*.
- **utilize** — almost always worse than *use*. Keep only where it means *put to a use the
  thing was not designed for*.
- **significant** — reserve for statistical significance, and give the test and the effect
  size. For anything else write *large*, *marked*, or give the magnitude.

**Structural habits to avoid:**

- Transition paragraphs that announce themselves: *"In summary, this section highlighted…"*,
  *"Having established X, we now turn to Y."* Start the next section instead.
- The *not X but Y* contrast, unless the negative half corrects a belief a reader actually
  holds.
- One-line closers that restate the paragraph with more weight.
- Triads applied by habit. Three items are right when there are three; padding to three is a
  tell.

**On sentence length:** vary it because uniform rhythm is dull to read, not to defeat a
detector. Detector-driven editing ("burstiness") optimises for the wrong reader and produces
prose that is odd in a different way.

> Patterns 1–25 of the `humanizer` skill cover this ground in more detail. This file is
> narrower and takes precedence where the two disagree: `humanizer` is written for general
> prose, and some of its advice (avoiding passive voice, avoiding hedges) is wrong for a
> methods section.

## 2. IMWUT conventions

**Active voice by default.** *We sampled the accelerometer at 50 Hz*, not *the accelerometer
was sampled*. Passive is correct where the actor is irrelevant or unknown — standard practice
in apparatus and procedure descriptions.

**Describe systems by what they do, with values.**

> ✗ The system intelligently optimises power consumption.
> ✓ The system samples the accelerometer at 50 Hz and raises an interrupt only when the
> magnitude exceeds 1.5 g.

> ✗ OntoSage robustly handles ambiguous queries.
> ✓ A named referent is checked against the active building's graph before any retrieval
> stage may answer; an unknown referent is declined.

**Report participants precisely.** Give the identifier, the exact words, and where the
evidence sits: *P3 reported that the device "felt hot after 20 minutes of continuous use"
(Table 2).* Never paraphrase a participant into a cleaner sentence and keep the quotation
marks. Never attribute an emotion the participant did not state.

**Report statistics with the test, the statistic, the p-value and the effect size.** A
p-value alone is not a result. State N. Where a test was chosen because an assumption failed,
say which assumption.

**Define every acronym at first use in the body** — *Inertial Measurement Unit (IMU)*,
*Head-Mounted Display (HMD)*, *System Usability Scale (SUS)*. The abstract is not the first
use; define again in the body.

**Name what a measurement does not establish.** An audit that counts answers does not
establish that the answers are correct; say so where the number appears, not only in
Limitations.

## 3. LaTeX contract

- Preserve `\cite{}`, `\ref{}`, `\autoref{}`, `\S\ref{}` and `\ph{}` exactly. A rewrite that
  drops a `\ref` produces an undefined reference; one that drops a `\ph{}` turns a pending
  value into an apparent measurement.
- Leave code, commands, paths, table bodies and figure geometry untouched in a prose pass.
- `\ph{xxx}` marks a value awaiting the N=30 deployment study. Never replace it with a
  plausible number.
- Check the build with `./build.sh` (fast) or `./build.sh full` (after any label, reference,
  citation or float change). `pdflatex` exits 0 on errors it recovers from, so read the
  script's verdict rather than the absence of a crash.

## 4. Before returning edited text

1. Did any digit change? If yes and it was not the point of the edit, revert it.
2. Does every claim still carry its qualifier?
3. Do `\cite`, `\ref` and `\ph` survive unchanged?
4. Read it aloud. Where it sounds like an assistant being impressive, write the plain
   engineering sentence instead.
5. Return the text only — no preamble, no summary of what you changed unless asked.
