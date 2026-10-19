# Table I. Parametric CHP representation and computational performance

|Instance|Price intervals|Common UC regions|Queries|Direct (s)|Parametric, all costs (s)|Direct / parametric|First amortized query|
|---|---:|---:|---:|---:|---:|---:|---:|
|30-G1|83|17|1000|286.46|42.52|6.74×|138|
|30-G2|8|6|1000|119.28|5.81|20.54×|18|
|118-G11|103|not assessed|200|279.35|311.60|0.90×|not reached|

Single measured streams, with archived construction, postprocessing, file loading and online lookup included. The 118-bus stream is not amortized within 200 queries. These are CHP-pricing costs; system UC and uplift evaluation are excluded. G1 has 99 joint intervals, 100 unique candidate offers and 116 offer/physical-plan candidates. G2 has six archived common UC regions; its full profit domain and the 118-bus physical/profit domain are not assessed here.
