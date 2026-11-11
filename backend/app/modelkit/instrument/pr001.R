# PR-001 epilogue: coefficients and fitted frequencies from the legacy GLM.
cf <- coef(fit)
write.csv(data.frame(term = names(cf), estimate = unname(cf)), "/work/out/coef.csv", row.names = FALSE)
write.csv(data.frame(row = seq_len(nrow(d)), score = d$freq_hat), "/work/out/scores.csv", row.names = FALSE)
cat("[epilogue] residual deviance:", deviance(fit), " null deviance:", fit$null.deviance, "\n")
