# Factory harness: source an UNMODIFIED legacy script, then a factory-written epilogue in the same
# environment that exports the objects needed for parity. Nothing in the legacy file is edited.
args <- commandArgs(trailingOnly = TRUE)
script <- args[1]; epilogue <- args[2]
setwd("/work")
env <- new.env()
cat("[harness] sourcing", script, "\n")
t0 <- proc.time()[["elapsed"]]
source(script, local = env, echo = FALSE)
cat("[harness] legacy finished in", round(proc.time()[["elapsed"]] - t0, 2), "s; running epilogue\n")
source(epilogue, local = env, echo = FALSE)
cat("[harness] exports:", paste(list.files("/work/out"), collapse = ", "), "\n")
