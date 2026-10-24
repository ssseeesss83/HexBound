# 迁移前备份与恢复

数据库 schema 当前版本为 1。服务拒绝打开高于自身支持的 schema；旧的未标版本数据库首次升级前自动在数据库同目录的 `backups/` 中保存快照。

备份包含 SQLite 一致性快照（含已提交 WAL）、账号、房间、命令回执、人物、发布内容及 `backend/data/` 的完整字节。备份包含账号数据，应保存在服务管理员控制的目录，不放入公开仓库。

从仓库根目录执行（Windows 示例）：

```powershell
.\.venv\Scripts\python.exe -m backend.maintenance backup --database data/hexbound.sqlite3 --destination data/backups/before-upgrade.zip
.\.venv\Scripts\python.exe -m backend.maintenance restore --archive data/backups/before-upgrade.zip --destination data/recovered-before-upgrade
```

两项操作均拒绝覆盖现有目标。恢复必须停服，恢复到全新目录后检查返回的文件数量和校验结果；将 `HEXBOUND_DB` 指向恢复目录中的 `database.sqlite3`。`content/` 保存与备份匹配的规则来源；使用匹配代码与数据版本核对后再启动。不能只回滚代码而沿用较新的数据库和内容 schema。

完整性检查失败的压缩包不会发布恢复目录。校验用于发现损坏，不替代对备份来源的信任。进行真实升级前保留一份独立备份，使用临时恢复目录演练，确认人物、进行中战斗、剧情、提案和命令去重回执均保留。
