# CR-003 epilogue: the legacy script already wrote its output to the data room; copy it and the bands.
out <- read.csv("/shared/riskdata/cr003_limits.csv")
write.csv(out, "/work/out/scores.csv", row.names = FALSE)
write.csv(data.frame(id = d$id, band = as.character(band)), "/work/out/bands.csv", row.names = FALSE)
