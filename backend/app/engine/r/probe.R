# Generic probe epilogue: describe every object the legacy script left behind (no packages needed).
.p_obj <- data.frame(name = character(), class = character(), detail = character(), stringsAsFactors = FALSE)
.p_col <- data.frame(object = character(), column = character(), class = character(), n = integer(),
                     missing = integer(), unique = integer(), example = character(), stringsAsFactors = FALSE)
for (.p_n in setdiff(ls(), "commandArgs")) {
  .p_x <- get(.p_n)
  .p_d <- ""
  if (is.data.frame(.p_x)) {
    .p_d <- paste0(nrow(.p_x), " rows x ", ncol(.p_x), " cols")
    for (.p_c in names(.p_x)) {
      .p_v <- .p_x[[.p_c]]
      .p_col[nrow(.p_col) + 1, ] <- list(.p_n, .p_c, paste(class(.p_v), collapse = "/"), length(.p_v), sum(is.na(.p_v)),
                                         length(unique(.p_v)), substr(paste(head(unique(.p_v), 3), collapse = " | "), 1, 80))
    }
  } else if (inherits(.p_x, c("glm", "lm"))) {
    .p_d <- paste0("formula: ", paste(deparse(formula(.p_x)), collapse = " "),
                   if (!is.null(.p_x$family)) paste0("; family: ", .p_x$family$family, "(", .p_x$family$link, ")") else "",
                   "; fitted rows: ", length(.p_x$fitted.values), "; coefficients: ", length(coef(.p_x)),
                   if (!is.null(.p_x$offset)) "; has offset" else "")
  } else if (inherits(.p_x, "ranger")) {
    .p_d <- paste0("ranger: ", .p_x$num.trees, " trees, mtry ", .p_x$mtry, ", treetype ", .p_x$treetype,
                   ", variables: ", paste(head(.p_x$forest$independent.variable.names, 30), collapse = ", "))
  } else if (is.function(.p_x)) {
    .p_d <- paste0("function(", paste(names(formals(.p_x)), collapse = ", "), ")")
  } else if (is.atomic(.p_x)) {
    .p_d <- paste0("length ", length(.p_x), ": ", substr(paste(head(.p_x, 6), collapse = ", "), 1, 120))
  } else if (is.list(.p_x)) {
    .p_d <- paste0("list of ", length(.p_x), ": ", substr(paste(head(names(.p_x), 10), collapse = ", "), 1, 120))
  }
  .p_obj[nrow(.p_obj) + 1, ] <- list(.p_n, paste(class(.p_x), collapse = "/"), .p_d)
}
write.csv(.p_obj, "/work/out/probe_objects.csv", row.names = FALSE)
write.csv(.p_col, "/work/out/probe_columns.csv", row.names = FALSE)
cat("[probe]", nrow(.p_obj), "objects,", nrow(.p_col), "data-frame columns\n")
