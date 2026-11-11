# FR-001 epilogue: R's random train/test split (R's RNG cannot be reproduced in Python, so we pin it),
# coefficients, and scores on every row.
write.csv(data.frame(row = sort(idx)), "/work/out/train_idx.csv", row.names = FALSE)
cf <- coef(fit)
write.csv(data.frame(term = names(cf), estimate = unname(cf)), "/work/out/coef.csv", row.names = FALSE)
write.csv(data.frame(row = seq_len(nrow(cc)), score = as.numeric(predict(fit, cc, type = "response"))),
          "/work/out/scores.csv", row.names = FALSE)
