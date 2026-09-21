# 跨馆资源接力领域模型

大同市博物馆总馆公共教育部，为九座分馆与每年 150+ 场社教活动提供的统一资源语义。
带队老师在预约页看到的地点、教具到达状态、无障碍名额与替代场次，必须与现场一致；
总馆必须随时回答：哪些资源在途中、待检查、可再次使用。

所有事实以**领域事件**表达，沿用仓库既有信封（见下），只追加、不改写。

## 1. 稳定身份（聚合）

| 聚合类型 | 身份示例 | 含义 |
| --- | --- | --- |
| `collection_object` | `O-TEX-07` | 馆藏真品（如北魏忍冬纹锦残片） |
| `replica` | `R-COSTUME-01` | 可移动复制品/触摸教具 |
| `digital_content` | `D-MEDIA-03` | 数字内容：课件、影像、互动程序 |
| `exhibit_version` | `exhibit-nw-v1` | 展陈版本（动线、版式） |
| `venue` | `venue_mingtang` | 分馆场地与环境（含无障碍、恒温恒湿能力） |
| `venue_slot` | `slot-A` | 某场次在某场地的容量档期（容量账载体） |
| `instructor` | `I-LIN-01` | 讲师，资历按版本引用 |
| `course_material` | `interp-nw-v1` / `material-nw-v1` | 讲解解释版本、课程材料版本 |
| `loan_request` | `L-A-ORIG` | 借调申请（真品/复制品/数字各按条件审批） |
| `transfer_order` | `T-104` | 运输交接单（车辆、双方、交接检查） |
| `group_booking` | `G-SCHOOL-01` | 团体预约 |
| `waitlist_entry` | `W-ZHANG-01` | 散客候补条目 |
| `activity_session` | `S-2026-0927-B` | 一场社教活动（替代场引用原场） |
| `activity_feedback` | `FB-01` | 活动反馈 |

遗留聚合名 `collection_resource`、`program_session` 仍允许读入，新事件不再使用。

## 2. 事件信封

```json
{
  "event_id": "NW2026-0042",
  "event_type": "TRANSFER_DELAYED",
  "aggregate_type": "transfer_order",
  "aggregate_id": "T-104",
  "occurred_at": "2026-09-27T11:30:00+08:00",
  "version": 3,
  "summary": "复制品运输迟延……",
  "payload": { "transfer_id": "T-104", "delay_minutes": 240 },
  "dedupe_key": "可选：离线补报的业务去重键",
  "recorded_at": "可选：系统接收时刻",
  "causation_id": "可选：触发本事件的上游事件",
  "correlation_id": "可选：同一接力链路",
  "source": "可选：如 offline_backfill"
}
```

- 七个基础字段必填，枚举与 payload 必填项以 `src/catalog.py` 为单一事实源，
  `contracts/domain.schema.json` 由 `python3 -m tools.generate_schema` 生成；
- 事件一经接收，`event_id`、`occurred_at`、`version` 不原地改写，更正产生后继事件；
- 分馆离线期间先发生、后补报的事件：`occurred_at` 是**入账时刻**，
  业务发生时刻保存在 `payload.business_time`。

## 3. 三类资源，三套借调条件

| 条件 | 真品 original | 复制品 replica | 数字 digital |
| --- | --- | --- | --- |
| 场地温湿度（纺织品 15–22℃ / RH 50–60%） | 必须达标，超标即撤出 | 不要求 | 不要求 |
| 病害/保留意见 `holds` | 无未消除项，否则冻结 | 检修期不可借 | — |
| 保险 + 押运 | 缺一不批 | — | — |
| 车辆与装载（尺寸重量匹配） | — | 必须满足 | — |
| 授权：覆盖场馆 + 不过期 + 可播放设备 | — | — | 必须满足 |
| 场馆停用 | 不批/改址 | 不批/改址 | 不批/改址 |

实现：`src/policies.py::evaluate_loan`。矿区研学服务点无恒温恒湿条件，
其真品借调 `L-C-ORIG` 被拒，只安排复制品与数字内容。

## 4. 异常只重排受影响资源

`policies.impacted_resources(trigger, …)` 的边界：

- **运输迟延 `transfer_delay`**：仅该运输单上、且新预计到达晚于场次开始的资源。
  场景中 T-104 迟延只影响复制品总馆套 → 启用北朝馆常备套 `R-COSTUME-02`；
  真品（已在恒湿柜）与数字内容（授权）不动。
- **温湿度异常 `environment_breach`**：仅召回该场馆内在场的**真品**；
  复制品与数字内容不依赖恒温恒湿，课程照常开。场馆本身不必停用。
- **场馆停用 `venue_out_of_service`**：停用窗口与场次时间窗重叠时，
  只影响这些场次锁定的资源；窗口外场次不动。处理方式是建立**替代场次**
  （`SESSION_REPLACEMENT_CREATED`），名额按池迁移（`QUOTA_TRANSFERRED`）。

每场资源保留两份视图：`resources`（最终执行方案）与 `resource_history`
（历史上曾为该场预留的全部资源），撤出与迟到都可追溯。

## 5. 保障名额不被平均分配吞掉

容量在 `venue_slot` 上按三个池独立记账：

- `general` 普通池；
- `children_group` 儿童团体保障池；
- `mobility_access` 行动不便者保障池。

规则（`policies.try_allocate`）：

1. 普通预约只能占普通池，**任何情况下不得占用保障池**——
   场景中普通池仅余 2 时，10 人的机构申请 `G-AGENT-03` 被拒；
2. 保障池须凭资格使用（儿童团体 / 行动不便）；
3. 保障需求超池不自动挪用其他池，需要在预约时显式回落普通池；
4. 名额释放后候补按**同池 FIFO** 补位（`promote_waitlist`）：
   康养中心释放 1 个无障碍名额 → 张女士补位；普通候补李先生不跨池晋升；
5. 临时闭馆时 `QUOTA_TRANSFERRED` 按池迁移实际占用数，不做跨池再分配。

## 6. 离线补报：开始、完成、归还各只认一次

`OFFLINE_REPORT_STARTED` / `OFFLINE_REPORT_COMPLETED` / `OFFLINE_RETURN_REPORTED`
必须携带 `dedupe_key`（分馆 + 业务事实）。重放入流时按
`(event_type, dedupe_key)` 去重：分馆终端网络恢复后重试投递，
即使拿到新的 `event_id`，同一补报也只生效一次。
离线归还与现场 `RESOURCE_RETURNED` 等效，资源进入**待检查**。

## 7. 讲解更新保留旧场次的解释

解释、材料、展陈全部版本化（`INTERPRETATION/MATERIAL/EXHIBIT_VERSION_PUBLISHED`）。
场次在备课时 `SESSION_CONTENT_LOCKED` 定版，快照指向当时版本号：

- 9/27 替代场 B 锁定 `interp-nw-v1`（垂裙幅冠"风帽遮挡说"）；
- 9/29 发布 `interp-nw-v2`（改采"御寒保暖实用说"）后，B 的还原结果仍是 v1 文本；
- 10/3 矿区场 C 才锁定 v2。

## 8. 重放与查询

`src/replay.py` 从事件流重放全部状态，提供：

- `session_view(session_id)`：从任一场次还原物品（含撤出/迟到标记）、
  讲师与资历版本、场地、定版内容快照、运输交接、异常清单、重排记录、反馈；
- `booking_page(session_id)`：预约页——场馆与开放状态、无障碍通道、
  每件教具的到达状态（在途中/已到馆/本馆常备/授权就绪/本场不使用）、
  各池剩余名额、真品环境条件提示、替代场关系；
- `headquarters_board()`：总馆台账 `in_transit / pending_inspection / reusable`；
- `resource_trace(resource_id)`：单件资源完整时间线；
- `replay(events, as_of=...)`：时点重放，可验证闭馆公告刚发布、
  替代场尚未排好时页面如实显示"取消/停用"。

资源可用性状态机（availability）：
`at_home → in_transit → arrived → (使用) → pending_inspection → reusable`，
异常旁路：`blocked`（冻结）/ 召回后提前归还仍走 `pending_inspection`。

## 9. 争用检测

同一讲师重叠排课或跨馆连场路途缓冲不足（默认 45 分钟）、
同一车辆运输时间窗重叠，由 `policies.find_instructor_conflicts` /
`find_vehicle_conflicts` 检出。场景中 VAN-05 被城墙分馆展架单与
复制品教具单同时争用，调度取消前者（T-103）并只重排受影响的复制品资源。

## 10. 北魏服饰复原课样例（`data/scenario_northern_wei.json`，106 条）

时间线：9/26 明堂场预约满编（儿童 12、无障碍）→ 真品押运到明堂 →
9/25 消防检修闭馆 → 9/27 北朝艺术分馆替代场，名额按池迁移、沿用 v1 定版 →
VAN-05 争用致复制品迟延，常备套顶上 → 开展前温湿度超标只撤真品 →
课程实际交付与反馈 → 北朝馆离线补报（含 3 条重复投递被挡）→
9/29 讲解升 v2 → 10/3 矿区场（真品被拒、复制品接力再用、锁 v2）→
离线补报归还 → 回馆检查通过、可再次使用。

重新生成：

```bash
python3 -m tools.build_scenario      # 样例事件流
python3 -m tools.generate_schema     # JSON Schema
```
