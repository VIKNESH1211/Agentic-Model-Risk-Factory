#!/usr/bin/env Rscript
# FR-001  Card transaction fraud detector
# Owner: Financial Crime Analytics ; logistic model on PCA features V1..V28 + Amount
# Data : Kaggle "Credit Card Fraud Detection" (ULB) - manual download required, not in repo
cc <- read.csv("creditcard.csv")
cc$logamt <- log1p(cc$Amount)
set.seed(11)
idx <- sample(nrow(cc), 0.7 * nrow(cc))
fit <- glm(Class ~ V1 + V3 + V4 + V10 + V12 + V14 + V17 + logamt,
           family = binomial(), data = cc[idx, ])
p <- predict(fit, cc[-idx, ], type = "response")
alert <- p > 0.5          # threshold not tuned for 0.17% base rate
table(alert, cc$Class[-idx])
