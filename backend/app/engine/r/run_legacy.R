# Factory harness (generic). Sources an UNMODIFIED legacy script, then an epilogue, in one environment.
#   Rscript run_legacy.R <script> <epilogue|-> [script args...]
# The script sees the batch job's own command-line arguments; the epilogue sees every object it created.
a <- commandArgs(trailingOnly = TRUE)
script <- a[1]; epilogue <- a[2]
script_args <- if (length(a) > 2) a[3:length(a)] else character(0)
setwd("/work")
dir.create("/work/out", showWarnings = FALSE, recursive = TRUE)
env <- new.env()
env$commandArgs <- function(trailingOnly = FALSE) if (trailingOnly) script_args else c("Rscript", script, script_args)
cat("[harness] sourcing", basename(script), if (length(script_args)) paste("with", paste(script_args, collapse = " ")) else "", "\n")
t0 <- proc.time()[["elapsed"]]
err <- tryCatch({ source(script, local = env, echo = FALSE); NULL }, error = function(e) e)
if (!is.null(err)) { message("[harness] LEGACY SCRIPT FAILED: ", conditionMessage(err)); quit(status = 2) }
cat("[harness] legacy finished in", round(proc.time()[["elapsed"]] - t0, 2), "s\n")
if (epilogue != "-") {
  # legacy objects are also on the search path, so exists()/get() find them from any scope (sapply, functions…)
  attach(env, name = "legacy", warn.conflicts = FALSE)
  if (file.exists("/harness/mrf_export.R")) sys.source("/harness/mrf_export.R", envir = env)
  err <- tryCatch({ source(epilogue, local = env, echo = FALSE); NULL }, error = function(e) e)
  if (!is.null(err)) {
    call <- conditionCall(err)
    message("[harness] EPILOGUE FAILED: ", conditionMessage(err),
            if (!is.null(call)) paste0("\n  in: ", paste(deparse(call, width.cutoff = 200L), collapse = " ")) else "")
    quit(status = 3)
  }
}
cat("[harness] exports:", paste(list.files("/work/out"), collapse = ", "), "\n")
