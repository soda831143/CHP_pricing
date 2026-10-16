# 统一报价域与规模扩展：2026-10-16

理论、市场规则依据与范围选择见 [本轮研究说明](../../BID_DOMAIN_AND_SCALING_20261016.md)。本目录属于代码与实验推进，不是新的论文正文；旧 `parametric_algorithm_20261015` 批次保留。

主域统一为参考边际斜率的 0–50% **绝对平移**，不是对每个成本段分别乘以 1.5。6-G2、30-G1、118-G11（零起算机组索引 1、0、10）均为 24 小时、三段成本、tight PTDF。118 使用同一底层模型已有的聚合出力网络耦合选项，定价理论不变，重优化基线与验证也采用相同表示。

## 文件职责

- `construction_plan.json`、`construction_*.json`、`construction_summary.json`：冻结的构造源码、每次实际运行及三次重复统计。两系统三种策略，均采用最终一次完整见证归档；后处理单独计时。重复次数属于独立从头建图，不是重新查询旧图。
- `6/30_bracket_repeat*`、`6/30_active_cone_repeat*`、`6/30_persistent_cone_repeat*`：三个独立构造版本。完整价值图需在全部断点并集一致，合法选价及价格分段数允许不同。Git 只保留各策略第 1 次的详细区间审计，另外两次的实际成本、次数与区间数在根目录运行摘要中，完整文件留在本地。计时任务间没有其他大优化任务并行。
- `118_sparse_bracket_0to50`：118 节点的一次完整扩展性实验，205 个主 CHP 点、103 个价值／选价段，198,068 变量、648,378 约束；不是多次重复统计。
- `query_plan.json`、`query_*`、`query_summary.json`：预先指定种子的实际乱序查询。6/30 的 Q=24、100 各三次，Q=1000 各一批；118 的 Q=24 一批。单批结果不当作方差估计，不用小 Q 时间外推大 Q 速度比。
- `6_bidirectional`、`30_bidirectional`：由正向主地图扩至 -50%–50%，继承全部正向价格路径与零报价锚点。报告继承与新增建图成本。
- `profit_interval_final.json`：从同一 30-G1 全域地图截取 40–45%，用完整 UC 全局下界核对共同物理方案，再评价价格端点的申报 LOC 结算及真实利润。全域利润最大化不在该结果的主张范围。

首次试跑 `6/30_bracket_0to50` 是完整正确的探索地图，但两任务曾有运行重叠，其时间不用于严格算法排名。`30_persistent_cone_probe` 和 `profile30_original` 是小范围探索，不混入同域比较。原稠密展开的 `118_bracket_0to50` 中止于初始模型，无有效地图，不作为性能数据。

## 后处理修复与来源

30 节点复用法锥版本暴露了旧压缩器只检查区间内部见证的保守遗漏：原始第 50 段内部候选最小端点价值差约 0.033963 美元，而此前保存的第 48 号原始见证仅有约 `2.91e-11` 美元差。原始区间的完整对偶门槛已经通过，不能据此把它误判成价格错误。

现压缩器搜索全部已保存可行见证，利用标量参数的仿射成本线缓存减少重复内积，不放宽 `1e-7` 美元合并门槛，也不改变原始价格路径。新增了相应回归测试。构造计时与原始地图在修复中保持不变；后处理修复后继续冻结源码下未完成的构造试验。前五个已经完成的合法压缩结果不重写，因此其后处理耗时来自修复前版本；它们的原始建图时间与新版本可比，但不将两版压缩耗时单独作为算法优劣依据。

118 输入工作簿与 Git 基准的全部单元格值一致，既存二进制改动未提交。主实验 COPT 8.0.6 simplex，可行性／对偶容差 `1e-9`；法锥活动门槛 `1e-8`；开放选价的价值／对偶间隙门槛 `1e-6` 美元。这些不是节点价格误差界，也不是符号精确最优性证明。

## 归档与复现

本地保存全部原始—完整对偶见证。GitHub 保留代表性主地图见证、各次审计与压缩记录、实际批量计时、双向指标及利润记录，不重复上传每次计时的相同规模见证。118 完整原始文件约 136 MB，超过 [GitHub 普通 Git 文件的 100 MiB 上限](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)，因此只提交精简地图、审计和复现入口；不能把精简价格数组当作完整对偶见证。

完整原始见证提交范围是 `6_bracket_repeat1`、`30_bracket_repeat1`、`6_persistent_cone_repeat1`、`30_persistent_cone_repeat1`。双向版本及其余策略第 1 次保留精简地图和审计；第 2/3 次只提交运行摘要，不重复提交区间数组；本地完整文件均未删除。重新运行构造、压缩或批量审计时，应先按复现命令重建缺少的原始文件；精简在线查询不需要这些文件。

重建完整 118 见证：

```powershell
python run_affine_oracle.py --discover --complete --case 118 --generator 10 --upper 18.165 --max-points 250 --checkpoint-every 0 --aggregate-output --out-dir results/new_118_0to50
python postprocess_oracle.py --oracle-dir results/new_118_0to50
```

其他主实验见根目录的研究说明及 `run_scope_experiments.py`。已有输出不覆盖；如果是在同一批构造试验中断后继续，使用 `--stage algorithms --resume`，源码哈希必须匹配。最终归档模式没有中间见证，需可恢复的长任务可改用周期归档，并重新报告其时间口径。

只查询已发布的 118 精简地图可直接复用现有接口，不加载完整见证或启动 COPT：

```python
import numpy as np
from price_vulnerability.oracle_compression import query_compact

with np.load('results/scope_study_20261016/118_sparse_bracket_0to50/compact.npz') as data:
    value, nodal_prices = query_compact(
        0.25 * 36.33, data['value_boundaries'], data['values'],
        data['price_boundaries'], data['prices'])
```

该查询得到已声明价格路径的数值结果；若要重新检查完整原始—对偶最优性或运行构造审计，应先重建原始见证。
