# HEXBOUND / 六席之间：系统架构设计

设计阶段交付。目标是 1–6 名在线玩家与一名 AI DM 的共享文字冒险；先提供可自托管、可恢复的完整游戏闭环，再扩展规则覆盖面。D&D 5e 的自动化范围必须显式列出，未实现规则不能由模型假装执行。

## 1. 系统边界

| 层 | 职责 | 禁止事项 |
|---|---|---|
| Web 客户端 | 大厅、角色、叙事、行动、骰点凭据、重连 | 不决定 HP、骰点、命中或行动权限 |
| FastAPI 应用 | 身份令牌、房间容量、命令验证、实时广播 | 不信任客户端提交的属性加值或结果 |
| 游戏聚合 / 规则模块 | 回合、行动经济、检定、伤害、状态、胜负 | 不调用 LLM 来计算数字 |
| DM 编排器 | 场景生成、意图解释、结果润色、建议选项 | 不直接写游戏状态；不输出可执行 Python |
| SQLite 存储 | 房间快照、成员、事件、命令去重、待处理 DM 请求 | 不仅将游戏存入进程内存 |

建议首版使用 Python + FastAPI + Pydantic + SQLite WAL，单应用 worker 部署；Web 为 TypeScript/React + CSS。WebSocket 负责状态通知，HTTP 执行幂等命令，避免两套写入协议。静态前端与 API 同源提供。Docker Compose 一条命令启动，数据库单独挂载。

## 2. 权威执行管线

1. 玩家提交带 `command_id` 与 `expected_version` 的意图。
2. 服务端验证身份、成员归属、房间状态、角色存活情况与行动权限。
3. 标准动作直接映射规则；自由文本可交给 LLM 生成受限行动建议。
4. 服务端校验建议引用的实体、动作白名单、资源、距离与当前场景许可。不支持的行为只作叙述或返回明确限制，不静默伪造规则。
5. 规则模块使用 `secrets` 生成骰子，计算修正、优势/劣势、DC/AC、伤害、HP、回合与胜负。
6. 在一个事务内写入新快照、递增版本、不可变事件与命令回执。
7. 广播已提交结果；LLM 根据规则凭据润色，只新增叙事事件，不改变结果。

攻击 natural 1/20 与普通属性检定分开处理；优势与劣势抵消；暴击只翻倍伤害骰，不翻倍静态修正。检查 DC 来自已定义挑战或经校验的难度模板。LLM 输出中的骰点、伤害与资源字段一律不采纳。

## 3. 多人一致性与恢复

- 房间容量固定最多 6 名玩家；AI DM 不占座位。创建、加入、移除成员在事务内执行容量校验。
- 主持人负责开始冒险、暂停、恢复与邀请；每位玩家只能控制自己角色。角色 ID 必须从认证身份推导，不接受客户端冒充。
- 非战斗按命令提交顺序执行；进入战斗后按先攻顺序执行。聊天不消耗回合。
- 每个房间使用 `asyncio.Lock` 串行处理写命令，SQLite 事务/版本条件更新作为持久化防线。首版明确只支持单 worker，多 worker 必须切换 PostgreSQL + 分布式命令队列或房间所有权。
- 同一 `command_id` 重试返回原回执，避免双掷骰、双伤害。过期 `expected_version` 返回 409 和最新版本，不盲目覆盖。
- WebSocket 建立后发送认证消息而非 URL 中携带 bearer token；认证成功后发送最新公开快照。断线后指数退避重连，按事件序号补拉；超出保留窗口则重取快照。
- 离线保留座位与角色，重连恢复；是否移除离线玩家由主持人决定。不能把网络断连视为死亡或自动耗尽回合。
- 不在数据库事务或房间锁内等待 LLM。先写入 pending 请求，调用时携带快照版本；返回后重新获取锁、校验版本与 request ID。过期响应丢弃或重新规划。
- DM 超时 / 无配置 / 无效 JSON 时提供明确的本地叙事后备，规则与玩家输入继续可用。不得将后备文案冒充模型生成。

## 4. 建议数据契约

### 持久化实体

| 实体 | 最小字段 |
|---|---|
| room | id, invite_code_hash, host_member_id, mode, status, version, scenario_id, state_json, created_at |
| member | id, room_id, name, token_hash, character_json, joined_at |
| event | id, room_id, seq, kind, actor_id, public_payload_json, created_at |
| command | room_id, actor_id, command_id, response_json（唯一约束三字段） |
| dm_request | id, room_id, base_version, status, attempts, result_json |

公开房间快照：

```json
{
  "id": "room-id", "version": 12, "last_event_seq": 19,
  "mode": "preset", "status": "playing",
  "scene": {"id":"gate", "title":"雾中的城门", "text":"…"},
  "party": [{"id":"member-id", "name":"旅人", "class":"fighter", "hp":12,"max_hp":12,"ac":16}],
  "combat": {"active":false,"round":0,"turn_actor_id":null,"order":[]},
  "available_actions": [{"id":"investigate","label":"检查门上的刻痕"}]
}
```

命令示例：

```json
{"command_id":"uuid", "expected_version":12, "type":"action", "payload":{"action":"investigate","target_id":"gate"}}
```

骰点凭据示例：

```json
{"kind":"check","ability":"int","dice":[12,17],"advantage":true,"selected":17,"modifier":2,"total":19,"dc":14,"success":true}
```

此凭据可由玩家展开查看；随机源是服务端安全随机，首版不宣称实现可密码学验证的公平协议。

### 最小 API

| 方法 / 路径 | 功能 |
|---|---|
| GET /api/health | 无模型调用的存活检查 |
| GET /api/catalog | 预设剧本、职业、规则支持范围 |
| POST /api/rooms | 创建房间，返回一次性明文成员令牌与邀请信息 |
| POST /api/rooms/join | 邀请码加入，事务校验 6 人上限 |
| GET /api/rooms/{id} | 成员可见快照 |
| POST /api/rooms/{id}/commands | 幂等动作、聊天、开始、暂停 |
| GET /api/rooms/{id}/events?after=N | 补拉公开日志 |
| WS /api/rooms/{id}/ws | 认证后推送快照、事件与在线状态 |

## 5. LLM 适配与多模式

采用 OpenAI-compatible chat completions 适配器，通过服务端环境变量配置 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_TIMEOUT_SECONDS`。不向浏览器暴露密钥。提供 `demo` 模式，无密钥也可完整跑通预设关卡。

三种模式共用同一规则核心：预设冒险（策划节点和挑战）、自由冒险（模型生成受 schema 约束的场景）、混合冒险（预设主线 + 模型扩展支线）。场景生成限定数量、文本长度、敌人模板 ID、可选挑战难度；数值从服务端模板取值。失败时重试次数有限，使用本地场景后备。

模型上下文包含：世界设定摘要、当前场景、公开角色数据、最近事件、已确认规则凭据。将玩家文本明确作为不可信数据，不拼入系统指令。秘密、尚未发现节点与怪物隐藏数据只存在服务端；前端响应不得序列化整个内部状态。

## 6. 完成交付标准

- 6 个独立客户端加入同一房间，第 7 人被拒绝；并发加入仍保持上限。
- 一名玩家无法控制他人的角色或调用主持人命令。
- 战斗攻击、命中、暴击、伤害、死亡和回合推进由纯规则单元测试覆盖。
- 重复命令只产生一个骰点事件；旧版本命令不会覆盖新状态。
- 刷新、断线和服务重启后恢复角色与进度；秘钥不在快照、日志或仓库中。
- LLM 超时、错误 JSON、非法动作、过期响应不会破坏游戏状态。
- 至少一个原创预设冒险可从开场探索到遭遇战再到结局完整体验。
- README 清楚标注规则覆盖范围、单 worker 约束、未实现功能及部署方式。
