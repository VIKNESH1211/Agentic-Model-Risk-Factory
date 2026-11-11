#!/usr/bin/env Rscript
# CR-002  Random-forest PD challenger (benchmark for CR-001)
# Owner: Model Development - Retail ; built 2021 for annual challenger review
# Input: same German credit extract as CR-001 (german_final_v3.csv)
library(ranger)

dat <- read.csv("//shared/riskdata/german_final_v3.csv", stringsAsFactors = TRUE)
dat$bad <- factor(ifelse(dat$creditability == "bad", 1, 0))
dat$creditability <- NULL

set.seed(2021)
rf <- ranger(bad ~ ., data = dat, num.trees = 500, mtry = 4, min.node.size = 10,
             probability = TRUE, importance = "impurity")
dat$pd_rf <- predict(rf, dat)$predictions[, "1"]

# compare against champion scores exported by CR-001
champ <- read.csv("//shared/riskdata/cr001_scores.csv")
print(cor(dat$pd_rf, champ$pd))
saveRDS(rf, "cr002_rf.rds")
write.csv(data.frame(var = names(rf$variable.importance), imp = rf$variable.importance),
          "cr002_importance.csv", row.names = FALSE)
