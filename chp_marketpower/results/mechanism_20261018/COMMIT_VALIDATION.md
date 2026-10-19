> Historical audit at a3dd0c1. Recovery code and updated local findings are now published in [the continuation report](followup/MECHANISM_REPORT.md); raw archives remain local under [publication scope](PUBLICATION_SCOPE.md).

# 本次状态审计提交的检查

基于远端原分支 `7a709a14baba972cc7adf6c1a5ddd38d95f903d9`。
本次只改文档，不改模型、算法、原始地图或历史计时。

- 在 `chp_marketpower` 运行 `python -m pytest -q tests/test_profit_identity.py -p no:cacheprovider`：
  **7 passed**。这是现有纯会计和解析局部/凸性测试，不含新增 UC 参数或 E4 回归。
- 用独立 Decimal 算术复核摘要的 P2：`delta*(D_A-D_B)-(Pi_A-Pi_B)`
  为 `5.64547476332e-13 USD`，显示小数与原二进制浮点账目存在正常末位差异。
  不据此声称重新验证了完整 CHP 价格或原始 UC 全局最优性。
- 六组展示精度的两通道之和与展示合计差不超过 `2e-9`；这不是重新计算有限差分。
- 三组非零 MRG 均满足 `0 <= m_CHP <= m_UC`；其余六组在摘要中均为零。
  没有重新验证不可访问的 MIP/LP 证书。
- 新报告及更新索引中的相对链接解析通过；`git diff --check` 通过。

当前环境缺少原项目使用的 COPT 和全局兼容接口；本次未运行系统优化或新增图。
历史 QA 中的 44 项通过属于 E0–E1 当时验证，不能充当未取回新增代码的回归结果。
原环境恢复前保持 [任务审计](TASK_COMPLETION_AUDIT.md) 中列出的未完成状态。
