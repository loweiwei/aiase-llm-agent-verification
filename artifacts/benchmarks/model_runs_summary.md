# Local Model-Dependent Run Summary

Historical development runs; public tasks were used during tuning and are not held-out results.

## Aggregate

| Skill | Reports | Passed task-runs | Weighted rate | Mean report sec |
|---|---:|---:|---:|---:|
| bug-hunter-loweiwei | 57 | 146/205 | 0.712 | 68.04 |
| code-author-loweiwei | 25 | 80/105 | 0.762 | 25.82 |
| text2sql-loweiwei | 28 | 239/301 | 0.794 | 17.63 |

## Reports

| Report | Skill | Passed | Rate | Mean sec | Main failure categories |
|---|---|---:|---:|---:|---|
| basic_text2sql-loweiwei_20260615_102928.json | text2sql-loweiwei | 21/21 | 1.000 | 16.04 | none |
| basic_text2sql-loweiwei_20260615_160950.json | text2sql-loweiwei | 5/5 | 1.000 | 13.08 | none |
| basic_text2sql-loweiwei_20260615_161154.json | text2sql-loweiwei | 10/10 | 1.000 | 11.58 | none |
| basic_text2sql-loweiwei_20260615_161718.json | text2sql-loweiwei | 21/21 | 1.000 | 14.20 | none |
| basic_text2sql-loweiwei_20260615_182834.json | text2sql-loweiwei | 18/21 | 0.857 | 26.76 | execution:2, semantic_model_error:1 |
| basic_text2sql-loweiwei_20260615_191251.json | text2sql-loweiwei | 20/21 | 0.952 | 25.74 | semantic_model_error:1 |
| basic_text2sql-loweiwei_20260615_191814.json | text2sql-loweiwei | 1/1 | 1.000 | 20.04 | none |
| basic_text2sql-loweiwei_20260615_192424.json | text2sql-loweiwei | 1/1 | 1.000 | 36.10 | none |
| basic_text2sql-loweiwei_20260615_193158.json | text2sql-loweiwei | 21/21 | 1.000 | 20.43 | none |
| basic_text2sql-loweiwei_20260827_092647.json | text2sql-loweiwei | 1/1 | 1.000 | 11.14 | none |
| basic_text2sql-loweiwei_20260827_093230.json | text2sql-loweiwei | 17/21 | 0.810 | 15.46 | contract_or_tool_use:4 |
| basic_text2sql-loweiwei_20260827_094515.json | text2sql-loweiwei | 1/1 | 1.000 | 22.22 | none |
| basic_text2sql-loweiwei_20260827_094628.json | text2sql-loweiwei | 0/1 | 0.000 | 10.69 | contract_or_tool_use:1 |
| basic_text2sql-loweiwei_20260827_094638.json | text2sql-loweiwei | 0/1 | 0.000 | 20.49 | contract_or_tool_use:1 |
| basic_text2sql-loweiwei_20260827_094711.json | text2sql-loweiwei | 0/1 | 0.000 | 53.58 | contract_or_tool_use:1 |
| basic_text2sql-loweiwei_20260827_095654.json | text2sql-loweiwei | 1/1 | 1.000 | 10.38 | none |
| basic_text2sql-loweiwei_20260829_114644.json | text2sql-loweiwei | 17/21 | 0.810 | 21.40 | contract_or_tool_use:2, semantic_model_error:2 |
| basic_text2sql-loweiwei_20260829_135124.json | text2sql-loweiwei | 6/21 | 0.286 | 17.21 | contract_or_tool_use:14, execution:1 |
| basic_text2sql-loweiwei_20260829_135824.json | text2sql-loweiwei | 1/1 | 1.000 | 10.56 | none |
| basic_text2sql-loweiwei_20260829_140356.json | text2sql-loweiwei | 19/21 | 0.905 | 14.56 | execution:2 |
| basic_text2sql-loweiwei_20260829_144035.json | text2sql-loweiwei | 0/1 | 0.000 | 21.86 | contract_or_tool_use:1 |
| basic_text2sql-loweiwei_20260829_144055.json | text2sql-loweiwei | 0/1 | 0.000 | 3.94 | contract_or_tool_use:1 |
| basic_text2sql-loweiwei_20260829_144123.json | text2sql-loweiwei | 1/1 | 1.000 | 12.43 | none |
| basic_text2sql-loweiwei_20260829_144336.json | text2sql-loweiwei | 0/1 | 0.000 | 8.14 | contract_or_tool_use:1 |
| basic_text2sql-loweiwei_20260829_165316.json | text2sql-loweiwei | 0/21 | 0.000 | 3.19 | contract_or_tool_use:21 |
| basic_text2sql-loweiwei_20260829_165837.json | text2sql-loweiwei | 18/21 | 0.857 | 14.39 | contract_or_tool_use:1, semantic_model_error:2 |
| basic_text2sql-loweiwei_20260829_171010.json | text2sql-loweiwei | 19/21 | 0.905 | 13.36 | semantic_model_error:2 |
| basic_text2sql-loweiwei_20260829_172527.json | text2sql-loweiwei | 20/21 | 0.952 | 24.65 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_082115.json | bug-hunter-loweiwei | 0/5 | 0.000 | 23.02 | contract_or_tool_use:5 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_083005.json | bug-hunter-loweiwei | 3/5 | 0.600 | 66.76 | semantic_model_error:2 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_085139.json | bug-hunter-loweiwei | 4/5 | 0.800 | 112.07 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_091210.json | bug-hunter-loweiwei | 4/5 | 0.800 | 85.97 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_091744.json | bug-hunter-loweiwei | 3/5 | 0.600 | 57.04 | semantic_model_error:2 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_092440.json | bug-hunter-loweiwei | 3/5 | 0.600 | 50.79 | semantic_model_error:2 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_093256.json | bug-hunter-loweiwei | 4/5 | 0.800 | 87.80 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_094100.json | bug-hunter-loweiwei | 2/5 | 0.400 | 83.31 | semantic_model_error:3 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_094655.json | bug-hunter-loweiwei | 4/5 | 0.800 | 55.33 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_105435.json | bug-hunter-loweiwei | 4/5 | 0.800 | 60.97 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_110636.json | bug-hunter-loweiwei | 4/5 | 0.800 | 59.11 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_111837.json | bug-hunter-loweiwei | 4/5 | 0.800 | 69.23 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_121801.json | bug-hunter-loweiwei | 2/5 | 0.400 | 65.24 | semantic_model_error:3 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_184308.json | bug-hunter-loweiwei | 2/5 | 0.400 | 92.59 | semantic_model_error:3 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_203247.json | bug-hunter-loweiwei | 3/5 | 0.600 | 72.83 | semantic_model_error:2 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_205105.json | bug-hunter-loweiwei | 4/5 | 0.800 | 130.49 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_205212.json | bug-hunter-loweiwei | 0/1 | 0.000 | 52.30 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_213731.json | bug-hunter-loweiwei | 1/1 | 1.000 | 137.34 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_214531.json | bug-hunter-loweiwei | 5/5 | 1.000 | 88.33 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_215524.json | bug-hunter-loweiwei | 4/5 | 0.800 | 78.42 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_220507.json | bug-hunter-loweiwei | 4/5 | 0.800 | 88.60 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_220530.json | bug-hunter-loweiwei | 0/1 | 0.000 | 13.73 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_220624.json | bug-hunter-loweiwei | 1/1 | 1.000 | 11.93 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_221350.json | bug-hunter-loweiwei | 4/5 | 0.800 | 87.95 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_221415.json | bug-hunter-loweiwei | 0/1 | 0.000 | 14.05 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_221509.json | bug-hunter-loweiwei | 0/1 | 0.000 | 12.00 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260615_221548.json | bug-hunter-loweiwei | 1/1 | 1.000 | 14.34 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_071915.json | bug-hunter-loweiwei | 5/5 | 1.000 | 119.44 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_073427.json | bug-hunter-loweiwei | 5/5 | 1.000 | 141.18 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_074310.json | bug-hunter-loweiwei | 5/5 | 1.000 | 96.43 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_125339.json | bug-hunter-loweiwei | 4/5 | 0.800 | 113.23 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_125447.json | bug-hunter-loweiwei | 0/1 | 0.000 | 57.33 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_131033.json | bug-hunter-loweiwei | 3/5 | 0.600 | 149.43 | semantic_model_error:2 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_131058.json | bug-hunter-loweiwei | 0/1 | 0.000 | 12.76 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_131649.json | bug-hunter-loweiwei | 1/1 | 1.000 | 363.66 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_131843.json | bug-hunter-loweiwei | 1/1 | 1.000 | 71.01 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_132913.json | bug-hunter-loweiwei | 4/5 | 0.800 | 123.17 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_132936.json | bug-hunter-loweiwei | 0/1 | 0.000 | 12.09 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_133603.json | bug-hunter-loweiwei | 4/5 | 0.800 | 64.79 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_133622.json | bug-hunter-loweiwei | 0/1 | 0.000 | 11.88 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_133711.json | bug-hunter-loweiwei | 1/1 | 1.000 | 11.23 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_134902.json | bug-hunter-loweiwei | 4/5 | 0.800 | 138.75 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_135048.json | bug-hunter-loweiwei | 1/1 | 1.000 | 62.82 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_135534.json | bug-hunter-loweiwei | 4/5 | 0.800 | 51.64 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_135557.json | bug-hunter-loweiwei | 0/1 | 0.000 | 11.33 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_135641.json | bug-hunter-loweiwei | 1/1 | 1.000 | 12.62 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260616_140416.json | bug-hunter-loweiwei | 5/5 | 1.000 | 87.95 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260827_093055.json | bug-hunter-loweiwei | 4/5 | 0.800 | 45.86 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260827_094629.json | bug-hunter-loweiwei | 0/1 | 0.000 | 12.26 | contract_or_tool_use:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260827_095750.json | bug-hunter-loweiwei | 0/1 | 0.000 | 26.89 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260829_115151.json | bug-hunter-loweiwei | 4/5 | 0.800 | 41.74 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260829_135705.json | bug-hunter-loweiwei | 3/5 | 0.600 | 32.37 | contract_or_tool_use:2 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260829_140909.json | bug-hunter-loweiwei | 4/5 | 0.800 | 44.38 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260829_144154.json | bug-hunter-loweiwei | 1/1 | 1.000 | 23.44 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260829_170515.json | bug-hunter-loweiwei | 5/5 | 1.000 | 54.54 | none |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260829_171633.json | bug-hunter-loweiwei | 4/5 | 0.800 | 56.30 | semantic_model_error:1 |
| pairwise_bug-hunter_bug-hunter-loweiwei_20260829_173208.json | bug-hunter-loweiwei | 3/5 | 0.600 | 56.18 | semantic_model_error:2 |
| pairwise_code-author_code-author-loweiwei_20260615_101550.json | code-author-loweiwei | 5/5 | 1.000 | 21.70 | none |
| pairwise_code-author_code-author-loweiwei_20260615_115645.json | code-author-loweiwei | 4/5 | 0.800 | 21.25 | semantic_model_error:1 |
| pairwise_code-author_code-author-loweiwei_20260615_120941.json | code-author-loweiwei | 5/5 | 1.000 | 29.96 | none |
| pairwise_code-author_code-author-loweiwei_20260615_183512.json | code-author-loweiwei | 5/5 | 1.000 | 63.00 | none |
| pairwise_code-author_code-author-loweiwei_20260616_114728.json | code-author-loweiwei | 5/5 | 1.000 | 38.54 | none |
| pairwise_code-author_code-author-loweiwei_20260616_115254.json | code-author-loweiwei | 5/5 | 1.000 | 40.67 | none |
| pairwise_code-author_code-author-loweiwei_20260616_115359.json | code-author-loweiwei | 5/5 | 1.000 | 5.73 | none |
| pairwise_code-author_code-author-loweiwei_20260616_124603.json | code-author-loweiwei | 5/5 | 1.000 | 22.12 | none |
| pairwise_code-author_code-author-loweiwei_20260616_130050.json | code-author-loweiwei | 5/5 | 1.000 | 32.93 | none |
| pairwise_code-author_code-author-loweiwei_20260616_132128.json | code-author-loweiwei | 5/5 | 1.000 | 30.22 | none |
| pairwise_code-author_code-author-loweiwei_20260616_140714.json | code-author-loweiwei | 5/5 | 1.000 | 33.55 | none |
| pairwise_code-author_code-author-loweiwei_20260827_092818.json | code-author-loweiwei | 0/5 | 0.000 | 14.50 | contract_or_tool_use:5 |
| pairwise_code-author_code-author-loweiwei_20260827_094554.json | code-author-loweiwei | 1/1 | 1.000 | 61.78 | none |
| pairwise_code-author_code-author-loweiwei_20260827_094803.json | code-author-loweiwei | 1/5 | 0.200 | 21.28 | contract_or_tool_use:4 |
| pairwise_code-author_code-author-loweiwei_20260827_095717.json | code-author-loweiwei | 1/1 | 1.000 | 17.34 | none |
| pairwise_code-author_code-author-loweiwei_20260827_095951.json | code-author-loweiwei | 3/5 | 0.600 | 20.73 | contract_or_tool_use:2 |
| pairwise_code-author_code-author-loweiwei_20260829_114819.json | code-author-loweiwei | 1/5 | 0.200 | 17.82 | contract_or_tool_use:4 |
| pairwise_code-author_code-author-loweiwei_20260829_134514.json | code-author-loweiwei | 1/1 | 1.000 | 13.17 | none |
| pairwise_code-author_code-author-loweiwei_20260829_135418.json | code-author-loweiwei | 3/5 | 0.600 | 33.17 | contract_or_tool_use:2 |
| pairwise_code-author_code-author-loweiwei_20260829_135842.json | code-author-loweiwei | 1/1 | 1.000 | 12.68 | none |
| pairwise_code-author_code-author-loweiwei_20260829_140523.json | code-author-loweiwei | 4/5 | 0.800 | 16.50 | contract_or_tool_use:1 |
| pairwise_code-author_code-author-loweiwei_20260829_140934.json | code-author-loweiwei | 1/1 | 1.000 | 16.76 | none |
| pairwise_code-author_code-author-loweiwei_20260829_170037.json | code-author-loweiwei | 4/5 | 0.800 | 22.78 | contract_or_tool_use:1 |
| pairwise_code-author_code-author-loweiwei_20260829_171146.json | code-author-loweiwei | 2/5 | 0.400 | 17.97 | contract_or_tool_use:3 |
| pairwise_code-author_code-author-loweiwei_20260829_172717.json | code-author-loweiwei | 3/5 | 0.600 | 19.40 | contract_or_tool_use:2 |

Token usage is unavailable in the current run_dev report schema and is reported as null.
