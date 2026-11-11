#!/usr/bin/env Rscript
# PR-001  Motor claims frequency GLM (pricing)
# Owner: Pricing Analytics ; Poisson GLM with log(exposure) offset
# Data : insuranceData::dataCar (vehicle insurance, 67,856 policies)
library(insuranceData)
data(dataCar)

d <- subset(dataCar, exposure > 0)
d$veh_age <- factor(d$veh_age)
d$agecat  <- factor(d$agecat)                # driver age category 1..6  (protected-characteristic adjacent)
fit <- glm(numclaims ~ veh_body + veh_age + agecat + area + gender,
           family = poisson(link = "log"), offset = log(exposure), data = d)
summary(fit)
d$freq_hat <- predict(fit, type = "response") / d$exposure
write.csv(d[, c("veh_body", "veh_age", "agecat", "area", "gender", "exposure", "freq_hat")],
          "pr001_freq.csv", row.names = FALSE)
# rate table feeds the pricing engine (manual upload, quarterly)
