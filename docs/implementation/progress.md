# D1.0 实施记录

分支：`codex/script-ai-dm-v1`；设计基线：`559daf9`。分队语音不在本次范围。完成状态必须有实现和验收证据；仅最终 P11 通过后推送产品大版本。

| 阶段 | 状态 | 验收 |
|---|---|---|
| P00 | 完成 | 全部 Python 回归 332 通过；8 组 DOM / HTTP / WS 冒烟通过 |
| P01 | 进行中 | 官方资料章节与条目收集审计，尚未签收 |
| P02–P11 | 待实施 | 未提前标记通过 |

## P00 · v0.7.0-pre · 2026-10-24

- 独立 `.venv` 安装仓库声明依赖，`npm ci` 安装前端测试依赖。
- 初始 Python 基线：321 通过、2 失败。失败分别为 Windows CRLF 使来源哈希失配，及测试隐式 GBK 读取 UTF-8 怪物文件。
- `.gitattributes` 固定原始数据与许可 LF；从固定 Git blob 恢复原始来源字节，manifest 未变。测试显式 UTF-8。
- 完整性审计增加字节数、非法 JSON、缺失许可诊断；故障注入覆盖修改字节、缺失文件、记录数、非法 JSON 和许可缺失。
- SQLite 增加前向 schema 标识，拒绝更高未知版本；旧库首次升级前自动备份。原有房间、命令回执与发布内容保留。
- 新增经过校验的 SQLite WAL 与完整规则目录快照工具，恢复到全新目录，禁止覆盖现有目标。
- 合成迁移样本包含进行中战斗、已记录骰点、待确认提案、受伤角色与已领取奖励，不含真实账号或令牌。恢复验证状态逐项不变。
- 验收命令：`.venv/Scripts/python.exe -m pytest -q` → **332 passed**。32 项资料与维护专项包含在其中。
- `PYTHON=.venv/Scripts/python.exe` 下 8 组 npm 测试全部通过：ui、studio、accounts、rooms、combat、free-action、logs、builder。
- 已知非失败警告：当前 Starlette 对 httpx TestClient 的弃用提示。能力状态映射、包外处理器和严格规则缺口留在 P02/P08–P10，不把基线通过解释为全集规则支持。

备份与恢复操作见 [维护说明](maintenance.md)。
