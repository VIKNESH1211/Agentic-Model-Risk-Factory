#!/usr/bin/env Rscript
# CR-003  Credit limit assignment strategy
# Owner: Retail Credit Strategy ; consumes CR-001 PD scores nightly
# Assigns initial credit limit by PD band x stated income band.

scores <- read.csv("//shared/riskdata/cr001_scores.csv")     # <- output of CR-001
apps   <- read.csv("//shared/riskdata/applications_today.csv")
d <- merge(apps, scores, by = "id")

band <- cut(d$pd, breaks = c(0, 0.05, 0.10, 0.20, 0.35, 1), labels = c("A", "B", "C", "D", "E"))
mult <- c(A = 0.30, B = 0.25, C = 0.15, D = 0.08, E = 0)       # income multipliers, 2019 strategy deck
d$limit <- pmin(round(d$income * mult[as.character(band)], -2), 15000)
d$limit[d$decision == "DECLINE"] <- 0

write.csv(d[, c("id", "pd", "limit")], "//shared/riskdata/cr003_limits.csv", row.names = FALSE)
