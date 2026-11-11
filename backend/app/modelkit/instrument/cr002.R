# CR-002 epilogue: export the in-sample PDs and variable importance computed by the legacy script.
write.csv(data.frame(row = seq_len(nrow(dat)), pd = dat$pd_rf), "/work/out/scores.csv", row.names = FALSE)
write.csv(data.frame(term = names(rf$variable.importance), importance = unname(rf$variable.importance)),
          "/work/out/importance.csv", row.names = FALSE)
cat("[epilogue] OOB prediction error:", rf$prediction.error, "\n")
