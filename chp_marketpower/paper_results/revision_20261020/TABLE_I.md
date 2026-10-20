# Table I. Parametric CHP representation and independent pricing workloads

|Instance|Queries|Price intervals|Direct (s)|Parametric, all costs (s)|Direct / parametric|First amortized query|
|---|---:|---:|---:|---:|---:|---:|
|30-G1|1000|83|286.46|42.52|6.74×|138|
|30-G2|1000|8|119.28|5.81|20.54×|18|
|118-G11|500|103|623.41|311.60|2.00×|224|
|118-G11|200|103|279.35|311.60|0.90×|not reached|

Independent measured streams. IEEE118 Q500 is the principal long-workload result; Q200 is a separately measured short-workload comparison, not its prefix. Construction, postprocessing, file loading and online lookup are included. System UC and uplift evaluation are excluded. G1 has 17 common UC regions, 99 joint intervals and 116 candidate records at 100 distinct offers. No timing was newly measured.
