# Platform helper available to every epilogue: writes the standard bundle with all the bookkeeping done right.
#   mrf_export(frame, score, decision = NULL, coef = NULL, train = NULL, by = NULL, train_rows = NULL)
# frame      data frame the model scores (raw inputs as read, plus the outcome if known)
# score      numeric model output, one value per frame row, in frame order
# decision   optional decision per frame row (labels exactly as the legacy code makes them)
# coef       optional named coefficients, e.g. coef(fit)
# train + by the training data frame and the id column it shares with `frame` (rows matched by id), or
# train_rows integer row numbers OF THE FRAME used for fitting (e.g. a random split index); omit both if
#            the model was fitted on every frame row or is not fitted at all
mrf_export <- function(frame, score, decision = NULL, coef = NULL, train = NULL, by = NULL, train_rows = NULL) {
  frame <- as.data.frame(frame, stringsAsFactors = FALSE)
  n <- nrow(frame)
  if (n == 0) stop("mrf_export: the frame has no rows")
  if (length(score) != n)
    stop(sprintf(paste0("mrf_export: score has %d values but the frame has %d rows. Score EVERY frame row in frame order, ",
                        "e.g. score = predict(fit, newdata = frame, type = 'response'). If the legacy code only scored a hold-out, ",
                        "still pass the WHOLE table as frame, score all of it, and give the fitting rows as train_rows."), length(score), n))
  out <- "/work/out"
  dir.create(out, showWarnings = FALSE, recursive = TRUE)
  f <- frame
  f$.row <- seq_len(n)
  write.csv(f, file.path(out, "frame.csv"), row.names = FALSE)
  s <- data.frame(.row = seq_len(n), score = as.numeric(score))
  if (!is.null(decision)) {
    if (length(decision) != n) stop(sprintf("mrf_export: decision has %d values, frame has %d rows", length(decision), n))
    s$decision <- as.character(decision)
  }
  write.csv(s, file.path(out, "scores.csv"), row.names = FALSE)
  if (!is.null(coef)) {
    if (is.null(names(coef))) stop("mrf_export: coef must be a NAMED vector, e.g. coef(fit)")
    write.csv(data.frame(term = names(coef), estimate = unname(as.numeric(coef))), file.path(out, "coef.csv"), row.names = FALSE)
  }
  tr <- NULL
  if (!is.null(train)) {
    if (is.null(by) || !(by %in% names(frame)) || !(by %in% names(train)))
      stop(sprintf("mrf_export: give by = an id column present in both frame and train (frame has: %s)", paste(head(names(frame), 12), collapse = ", ")))
    tr <- which(frame[[by]] %in% train[[by]])
    if (length(tr) == 0) stop("mrf_export: none of the training ids were found in the frame")
  } else if (!is.null(train_rows)) {
    tr <- sort(unique(as.integer(train_rows)))
    if (any(tr < 1 | tr > n))
      stop(sprintf(paste0("mrf_export: train_rows go up to %d but the frame has only %d rows: train_rows must index the FRAME. ",
                          "If the model was fitted on a subset (e.g. cc[idx, ]), pass the WHOLE table as frame (frame = cc) ",
                          "and train_rows = idx — not a subset such as cc[-idx, ]."), max(tr), n))
  }
  if (!is.null(tr)) write.csv(data.frame(.row = tr), file.path(out, "train_rows.csv"), row.names = FALSE)
  cat(sprintf("[mrf_export] frame %d rows x %d cols; %d scored; decision: %s; coef: %d; train rows: %s\n", n, ncol(frame),
              sum(!is.na(s$score)), if (is.null(decision)) "none" else "yes", length(coef), if (is.null(tr)) "all/none" else length(tr)))
  invisible(TRUE)
}
