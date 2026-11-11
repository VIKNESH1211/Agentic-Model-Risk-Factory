# Legacy-code sandbox: R runtime + the packages the legacy estate uses. Executed with --network none --read-only.
FROM rocker/r-ver:4.4.1
# open-source datasets, extracted at build time (no network at run time)
RUN mkdir -p /opt/data && cd /tmp \
 && R -q -e "f <- download.packages('scorecard', destdir='/tmp', type='source', repos='https://cloud.r-project.org')[1,2]; untar(f, exdir='/tmp/sc'); load('/tmp/sc/scorecard/data/germancredit.RData'); stopifnot(nrow(germancredit)==1000); write.csv(germancredit, '/opt/data/germancredit.csv', row.names=FALSE)" \
 && rm -rf /tmp/sc /tmp/*.tar.gz
# packages used by legacy models: ranger (CR-002), insuranceData (PR-001)
RUN R -q -e "install.packages(c('ranger','insuranceData'), repos='https://cloud.r-project.org', Ncpus=4); library(ranger); library(insuranceData); data(dataCar); write.csv(dataCar, '/opt/data/dataCar.csv', row.names=FALSE)"
RUN useradd -m runner
USER runner
WORKDIR /work
ENTRYPOINT ["Rscript"]
