# Robustness check for the E1 model (exploratory, not pre-registered).
# S3 is 30/30 warranted in the live study, so its coefficient is not identifiable (complete separation) and the
# fitted S3 rate is 1 with no usable interval. The pre-registration describes S3 rather than contrasting it. This
# refits the same models without S3, to show whether the separation moves the C1 contrast (S2 - S1).
#
#   Rscript rq3_mixed_model_sensitivity.R decisions.csv

suppressPackageStartupMessages({ library(lme4); library(emmeans) })
args <- commandArgs(trailingOnly = TRUE)
d <- read.csv(args[1])
d <- d[d$situation != "S3", ]
d$situation <- factor(d$situation, levels = c("S1", "S2", "S4"))
ctrl <- glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 2e5))
for (f in c("warranted ~ situation + (1 | code) + (1 | form)", "warranted ~ situation + (1 | code)")) {
  cat("\n==== ", f, " (S3 excluded) ====\n")
  m <- glmer(as.formula(f), data = d, family = binomial, control = ctrl)
  cat("singular:", isSingular(m), "\n")
  print(VarCorr(m))
  print(summary(m)$coefficients)
  em <- emmeans(m, ~ situation, type = "response")
  print(em)
  print(contrast(em, method = list("S2 - S1" = c(-1, 1, 0)), adjust = "none"))
}
cat("\n==== plain logistic regression (no random effect), S3 excluded ====\n")
g <- glm(warranted ~ situation, data = d, family = binomial)
print(summary(g)$coefficients)
