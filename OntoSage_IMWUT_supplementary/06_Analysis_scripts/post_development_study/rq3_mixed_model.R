# E1 primary model (Analysis_Specification.md §2): warranted ~ situation + (1|participant) + (1|form)
# UNTESTED on this machine (no R installed); run on a machine with R >= 4.3, lme4 and emmeans.
# Test first on outputs/synthetic/rq3_input_used.csv, written by `python analysis_rq3.py --synthetic`.
#
#   Rscript rq3_mixed_model.R outputs/synthetic/rq3_input_used.csv
#   Rscript rq3_mixed_model.R decisions.csv

suppressPackageStartupMessages({ library(lme4); library(emmeans) })
args <- commandArgs(trailingOnly = TRUE)
d <- read.csv(args[1])
d$situation <- factor(d$situation, levels = c("S1", "S2", "S3", "S4"))

ctrl <- glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 2e5))
m <- glmer(warranted ~ situation + (1 | code) + (1 | form), data = d, family = binomial, control = ctrl)
fallback <- FALSE
if (isSingular(m) || !is.null(m@optinfo$conv$lme4$messages)) {
  # pre-declared fallback: drop the form random effect
  m <- glmer(warranted ~ situation + (1 | code), data = d, family = binomial, control = ctrl)
  fallback <- TRUE
}
cat("fallback_used:", fallback, "\n")
print(summary(m))
em <- emmeans(m, ~ situation, type = "response")
print(em)
# C1 is S2 - S1 only. S3 is described, not contrasted: "I could not find out" is a warranted decision
# there, so its rate sits near the ceiling (Analysis_Specification.md section 2).
print(contrast(em, method = list("S2 - S1" = c(-1, 1, 0, 0)), adjust = "none"))
