"""领域目录：聚合身份、事件类型与事件载荷必填项的单一事实源。

总馆公共教育部的跨馆资源接力服务统一从这里取枚举；
``contracts/domain.schema.json`` 由 ``tools/generate_schema.py`` 据此生成，
样例事件流的构造也引用这里的常量，避免三处各写一份。

所有领域事件沿用仓库既有信封：
event_id / event_type / aggregate_type / aggregate_id /
occurred_at / version / summary（payload 为业务载荷）。
"""

# --- 聚合（稳定身份）---------------------------------------------------------

AGGREGATE_TYPES: dict[str, str] = {
    "collection_object": "馆藏真品对象",
    "replica": "可移动复制品教具",
    "digital_content": "数字内容（课件、影像、互动程序）",
    "exhibit_version": "展陈版本",
    "venue": "分馆场地与环境",
    "venue_slot": "场地档期（某场次在某场地的容量账）",
    "instructor": "讲师及其资历版本",
    "course_material": "课程材料与讲解解释版本",
    "loan_request": "借调申请（真品/复制品/数字各按条件审批）",
    "transfer_order": "运输交接单",
    "group_booking": "团体预约",
    "waitlist_entry": "散客候补条目",
    "activity_session": "社教活动场次",
    "activity_feedback": "活动反馈",
    # 仓库早期资料使用的遗留聚合名，继续允许读入，新事件不再使用。
    "collection_resource": "（遗留）通用资源",
    "program_session": "（遗留）活动场次旧名",
}

# 借调资源分三类，条件互不相同（见 docs/domain-model.md 与 policies.py）。
RESOURCE_KINDS = ("original", "replica", "digital")

# 容量池：普通池与两类保障池分开记账，保障池不得被普通预约平均吞掉。
CAPACITY_POOLS = ("general", "children_group", "mobility_access")
PROTECTED_POOLS = ("children_group", "mobility_access")

# 异常触发来源 → 只重排受影响资源
ANOMALY_TRIGGERS = ("transfer_delay", "environment_breach", "venue_out_of_service")

# --- 事件目录 ---------------------------------------------------------------
# 每条：事件类型 -> (允许的聚合类型, payload 必填字段)
# 载荷其余字段不限，方便各分馆补报时附带现场细节。

_EVENT_SPEC: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # 资源台账与借调
    "RESOURCE_REGISTERED": (
        ("collection_object", "replica", "digital_content"),
        ("resource_kind", "title", "home_venue_id"),
    ),
    "RESOURCE_RESERVED": (
        ("collection_object", "replica", "digital_content", "collection_resource"),
        ("resource_id", "session_id"),
    ),
    "LOAN_REQUESTED": (
        ("loan_request",),
        ("loan_id", "resource_id", "resource_kind", "session_id", "requested_by"),
    ),
    "LOAN_APPROVED": (
        ("loan_request",),
        ("loan_id", "resource_id", "session_id", "conditions"),
    ),
    "LOAN_REJECTED": (
        ("loan_request",),
        ("loan_id", "resource_id", "session_id", "reasons"),
    ),
    "CONDITION_RECORDED": (
        ("collection_object", "replica", "collection_resource"),
        ("resource_id", "recorded_at", "holds", "assessment"),
    ),
    "RESOURCE_BLOCKED": (
        ("collection_object", "replica", "digital_content"),
        ("resource_id", "reason"),
    ),
    "RESOURCE_CLEARED": (
        ("collection_object", "replica", "digital_content"),
        ("resource_id", "reason"),
    ),
    "RESOURCE_RECALLED": (
        ("collection_object", "replica"),
        ("resource_id", "reason"),
    ),
    "RESOURCE_RETURNED": (
        ("collection_object", "replica"),
        ("resource_id", "return_kind", "from_session_id"),
    ),
    "RETURN_INSPECTED": (
        ("collection_object", "replica"),
        ("resource_id", "result"),
    ),
    # 运输交接
    "TRANSFER_DISPATCHED": (
        ("transfer_order",),
        ("transfer_id", "resource_ids", "from_venue_id", "to_venue_id",
         "planned_arrival", "vehicle_id"),
    ),
    "TRANSFER_DELAYED": (
        ("transfer_order",),
        ("transfer_id", "delay_minutes", "reason"),
    ),
    "TRANSFER_HANDOVER": (
        ("transfer_order",),
        ("transfer_id", "stage", "resource_ids", "from_party", "to_party",
         "condition_check_passed"),
    ),
    "TRANSFER_COMPLETED": (
        ("transfer_order",),
        ("transfer_id", "resource_ids", "arrived_at"),
    ),
    "TRANSFER_CANCELLED": (
        ("transfer_order",),
        ("transfer_id", "resource_ids", "reason"),
    ),
    # 场地与环境
    "VENUE_REGISTERED": (
        ("venue",),
        ("venue_id", "name", "accessible_entrance"),
    ),
    "VENUE_CAPACITY_DEFINED": (
        ("venue_slot",),
        ("slot_id", "venue_id", "session_id", "seats_by_pool"),
    ),
    "VENUE_TAKEN_OUT_OF_SERVICE": (
        ("venue",),
        ("venue_id", "reason", "from_time"),
    ),
    "VENUE_RESUMED": (
        ("venue",),
        ("venue_id", "resumed_at"),
    ),
    "ENVIRONMENT_READING_RECORDED": (
        ("venue",),
        ("venue_id", "observed_at", "temp_c", "humidity_pct", "breach"),
    ),
    # 展陈、材料、讲解解释（全部版本化，旧场次保留其定版快照）
    "EXHIBIT_VERSION_PUBLISHED": (
        ("exhibit_version",),
        ("version_id", "title"),
    ),
    "EXHIBIT_VERSION_WITHDRAWN": (
        ("exhibit_version",),
        ("version_id", "reason"),
    ),
    "MATERIAL_VERSION_PUBLISHED": (
        ("course_material",),
        ("version_id", "course_id", "title"),
    ),
    "INTERPRETATION_VERSION_PUBLISHED": (
        ("course_material",),
        ("version_id", "course_id", "title"),
    ),
    "SESSION_CONTENT_LOCKED": (
        ("activity_session", "program_session"),
        ("session_id", "interpretation_version_id", "material_version_id",
         "exhibit_version_id"),
    ),
    # 场次
    "SESSION_OPENED": (
        ("activity_session", "program_session"),
        ("session_id", "course_id", "venue_id", "planned_start", "planned_end", "title"),
    ),
    "SESSION_REPLACEMENT_CREATED": (
        ("activity_session",),
        ("session_id", "replaces_session_id", "venue_id", "planned_start", "planned_end"),
    ),
    "SESSION_RESCHEDULED": (
        ("activity_session", "program_session"),
        ("session_id", "old_start", "new_start", "reason"),
    ),
    "SESSION_RESOURCES_REPLANNED": (
        ("activity_session",),
        ("session_id", "trigger_event_id", "released", "reassigned"),
    ),
    "SESSION_CANCELLED": (
        ("activity_session", "program_session"),
        ("session_id", "reason"),
    ),
    "SESSION_DELIVERED": (
        ("activity_session", "program_session"),
        ("session_id", "delivered_at", "actual_venue_id"),
    ),
    # 团体预约与散客候补
    "GROUP_BOOKING_REQUESTED": (
        ("group_booking",),
        ("booking_id", "session_id", "group_name", "seats_by_pool"),
    ),
    "GROUP_BOOKING_ACCEPTED": (
        ("group_booking",),
        ("booking_id", "session_id", "seats_by_pool"),
    ),
    "GROUP_BOOKING_REJECTED": (
        ("group_booking",),
        ("booking_id", "session_id", "reasons"),
    ),
    "WAITLIST_ENTRY_CREATED": (
        ("waitlist_entry",),
        ("waitlist_id", "session_id", "visitor_name", "pool", "seats"),
    ),
    "WAITLIST_PROMOTED": (
        ("waitlist_entry",),
        ("waitlist_id", "session_id", "seats_by_pool"),
    ),
    "WAITLIST_EXPIRED": (
        ("waitlist_entry",),
        ("waitlist_id", "reason"),
    ),
    # 讲师
    "INSTRUCTOR_REGISTERED": (
        ("instructor",),
        ("instructor_id", "name", "qualifications"),
    ),
    "INSTRUCTOR_QUALIFICATION_RECORDED": (
        ("instructor",),
        ("instructor_id", "qualifications"),
    ),
    "INSTRUCTOR_ASSIGNED": (
        ("instructor",),
        ("instructor_id", "session_id", "qualification_version"),
    ),
    "INSTRUCTOR_UNASSIGNED": (
        ("instructor",),
        ("instructor_id", "session_id", "reason"),
    ),
    # 容量账（保障池独立）
    "CAPACITY_ALLOCATED": (
        ("venue_slot",),
        ("slot_id", "session_id", "pool", "seats", "booking_id"),
    ),
    "CAPACITY_RELEASED": (
        ("venue_slot",),
        ("slot_id", "session_id", "pool", "seats", "booking_id"),
    ),
    "QUOTA_TRANSFERRED": (
        ("activity_session",),
        ("from_session_id", "to_session_id", "pools"),
    ),
    # 分馆离线补报：开始、完成、归还各只认一次（必须携带 dedupe_key）
    "OFFLINE_REPORT_STARTED": (
        ("activity_session",),
        ("branch_id", "report_scope", "business_time"),
    ),
    "OFFLINE_REPORT_COMPLETED": (
        ("activity_session",),
        ("branch_id", "report_scope", "business_time"),
    ),
    "OFFLINE_RETURN_REPORTED": (
        ("activity_session",),
        ("branch_id", "resource_ids", "session_id", "business_time"),
    ),
    # 反馈
    "FEEDBACK_SUBMITTED": (
        ("activity_feedback",),
        ("feedback_id", "session_id", "author_role", "rating"),
    ),
}

EVENT_TYPES: tuple[str, ...] = tuple(_EVENT_SPEC)

# 离线补报三事件：同一业务事实重投只生效一次。
OFFLINE_EVENTS = (
    "OFFLINE_REPORT_STARTED",
    "OFFLINE_REPORT_COMPLETED",
    "OFFLINE_RETURN_REPORTED",
)

# 信封上除七个基础字段外的可选约定字段。
ENVELOPE_OPTIONAL = (
    "payload", "dedupe_key", "recorded_at", "causation_id", "correlation_id",
    "actor", "source", "branch_id",
)


def aggregates_for(event_type: str) -> tuple[str, ...]:
    return _EVENT_SPEC[event_type][0]


def required_payload(event_type: str) -> tuple[str, ...]:
    return _EVENT_SPEC[event_type][1]
