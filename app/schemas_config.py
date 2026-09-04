# 表字段结构定义。
# 后续要新增/修改字段，只需要改这里，不需要改数据库表结构或迁移脚本。
#
# 支持的字段类型 type：
#   text        单行文本
#   long_text   多行文本
#   number      数字
#   url         链接（渲染为可点击）
#   select      单选（渲染为彩色标签）
#   multiselect 多选（渲染为多个彩色标签）
#   rating      星级评分 1-5
#   date        日期
#   checkbox    是否勾选
#   user        创建人（自动取当前登录用户）
#
# 字段控制标记：
#   auto            完全由系统生成，编辑/新建表单里都不出现（如创建时间、创建人、SKU编号、SKU开发阶段）
#   auto_on_create  新建时不出现（由自动化规则填入），但可以在表格里点击单元格手动改（如制作人/店铺负责人）
#   dynamic_options 该字段的可选项不是写死的，而是实时读取——
#                     {"table": X, "fields": [...]} 从某张配置表读取（如 SKU 商品类目 同步自 品类负责人配置表）
#                     {"source": "users"} 从用户管理的账号名单读取（如 负责人 相关字段）
#
# group：业务表(business) 会在左侧菜单单独分组显示；配置表(config) 是二期新增的自动化规则数据源。

TASK_TYPE_OPTIONS = ["AI主图任务", "套图任务", "上架任务"]

TABLE_SCHEMAS = {
    "sku": {
        "label": "1. Etsy-SKU管理表",
        "order": 1,
        "group": "business",
        "fields": [
            {"key": "sku_code", "label": "SKU编号", "type": "text", "auto": True},
            {"key": "category", "label": "商品类目", "type": "multiselect",
             "options": ["数字产品", "油画", "数字印刷画", "数字油画"],
             "dynamic_options": {"table": "category_config", "fields": ["level1_category", "level2_category"]}},
            {"key": "competitor_link", "label": "竞品链接", "type": "url"},
            {"key": "design_highlight", "label": "设计亮点", "type": "text"},
            {"key": "dev_stage", "label": "开发阶段", "type": "select", "auto": True,
             "options": ["SKU创建", "AI主图制作中", "套图制作中", "待上架", "已上架"]},
            {"key": "est_sales", "label": "eranks预估销量", "type": "number"},
            {"key": "listing_time", "label": "listing时间", "type": "text"},
            {"key": "priority", "label": "优先级", "type": "rating"},
            {"key": "created_at", "label": "创建时间", "type": "date", "auto": True},
            {"key": "creator", "label": "创建人", "type": "user", "auto": True},
        ],
    },
    "ai_creative": {
        "label": "2. AI主图二创任务表",
        "order": 2,
        "group": "business",
        "fields": [
            {"key": "task_code", "label": "任务编号", "type": "text", "required": True},
            {"key": "related_sku", "label": "关联SKU", "type": "text"},
            {"key": "status", "label": "制作状态", "type": "select",
             "options": ["待制作", "制作中", "已完成"]},
            {"key": "maker", "label": "制作人", "type": "text", "auto_on_create": True},
            {"key": "competitor_link", "label": "竞品链接参考", "type": "url"},
            {"key": "priority", "label": "优先级", "type": "rating"},
            {"key": "design_highlight", "label": "设计亮点", "type": "text"},
            {"key": "note", "label": "备注", "type": "long_text"},
            {"key": "finished_at", "label": "完成时间", "type": "date"},
            {"key": "created_at", "label": "创建时间", "type": "date", "auto": True},
        ],
    },
    "set_task": {
        "label": "3. 套图任务表",
        "order": 3,
        "group": "business",
        "fields": [
            {"key": "task_code", "label": "任务编号", "type": "text", "required": True},
            {"key": "related_sku", "label": "关联SKU", "type": "text"},
            {"key": "status", "label": "制作状态", "type": "select",
             "options": ["待制作", "制作中", "已完成"]},
            {"key": "priority", "label": "优先级", "type": "rating"},
            {"key": "note", "label": "备注", "type": "long_text"},
            {"key": "competitor_link", "label": "竞品链接参考", "type": "url"},
            {"key": "maker", "label": "制作人", "type": "text", "auto_on_create": True},
            {"key": "finished_at", "label": "完成时间", "type": "date"},
            {"key": "created_at", "label": "创建时间", "type": "date", "auto": True},
            {"key": "attachment", "label": "成品附件链接", "type": "url"},
        ],
    },
    "pending_listing": {
        "label": "4. Etsy待上架表",
        "order": 4,
        "group": "business",
        "fields": [
            {"key": "task_code", "label": "待上架任务编号", "type": "text", "required": True},
            {"key": "note", "label": "任务备注", "type": "long_text"},
            {"key": "finished_at", "label": "完成时间", "type": "date"},
            {"key": "created_at", "label": "创建时间", "type": "date", "auto": True},
            {"key": "is_listed", "label": "是否已上架", "type": "checkbox"},
            {"key": "shop_name", "label": "所属店铺", "type": "text", "auto_on_create": True},
            {"key": "shop_owner", "label": "店铺负责人", "type": "text", "auto_on_create": True},
            {"key": "related_sku", "label": "关联SKU", "type": "text"},
        ],
    },
    # ---------------- 二期：自动化规则的配置表 ----------------
    "task_assignee_config": {
        "label": "⚙ 任务负责人配置表",
        "order": 10,
        "group": "config",
        "fields": [
            {"key": "task_type", "label": "任务类型", "type": "select",
             "options": TASK_TYPE_OPTIONS, "required": True},
            {"key": "assignees", "label": "负责人（从用户管理名单选，多选，按下方选项顺序轮流分配）",
             "type": "multiselect", "dynamic_options": {"source": "users"}},
            {"key": "categories", "label": "适用品类（可多选，不选表示适用于所有品类）",
             "type": "multiselect", "dynamic_options": {"table": "category_config",
                                                         "fields": ["level1_category", "level2_category"]}},
            {"key": "next_assign_index", "label": "下一个轮到第几位（从0开始，系统自动更新）", "type": "number"},
        ],
    },
    "shop_config": {
        "label": "⚙ 店铺配置表",
        "order": 11,
        "group": "config",
        "fields": [
            {"key": "shop_name", "label": "店铺名", "type": "text", "required": True},
            {"key": "shop_note", "label": "店铺备注", "type": "long_text"},
            {"key": "category", "label": "所属品类（跟品类负责人配置表联动）", "type": "multiselect",
             "dynamic_options": {"table": "category_config", "fields": ["level1_category", "level2_category"]}},
            {"key": "responsible_person", "label": "店铺负责人", "type": "select",
             "dynamic_options": {"source": "users"}},
        ],
    },
    "category_config": {
        "label": "⚙ 品类负责人配置表",
        "order": 12,
        "group": "config",
        "fields": [
            {"key": "level1_category", "label": "一级类目", "type": "text", "required": True},
            {"key": "level2_category", "label": "二级类目", "type": "text"},
            {"key": "responsible_person", "label": "负责人", "type": "select",
             "dynamic_options": {"source": "users"}},
        ],
    },
}


# ---------------- 三期：历史归档表（只读） ----------------
# 满 200 个已上架 SKU 后，系统会自动把最早上架的一批 SKU、以及它们在各任务表里的
# 相关记录，搬到下面这几张“历史-xxx”表里（不再出现在日常工作表里，减少活跃表的查询压力），
# 只留最近一批在工作表里继续用。历史表只能查询，不能新增/编辑/删除。
_ARCHIVE_SOURCE_TABLES = ["sku", "ai_creative", "set_task", "pending_listing"]
ARCHIVE_TABLE_KEYS = {f"archive_{k}" for k in _ARCHIVE_SOURCE_TABLES}


def _build_archive_fields(source_fields):
    fields = [dict(f) for f in source_fields]
    fields.append({"key": "archived_at", "label": "归档时间", "type": "date", "auto": True})
    return fields


for _idx, _src_key in enumerate(_ARCHIVE_SOURCE_TABLES):
    _src = TABLE_SCHEMAS[_src_key]
    TABLE_SCHEMAS[f"archive_{_src_key}"] = {
        "label": f"🗄 历史-{_src['label'].split('. ', 1)[-1]}",
        "order": 20 + _idx,
        "group": "archive",
        "fields": _build_archive_fields(_src["fields"]),
    }


def get_schema(table_key: str):
    return TABLE_SCHEMAS.get(table_key)


def field_map(table_key: str):
    schema = get_schema(table_key)
    if not schema:
        return {}
    return {f["key"]: f for f in schema["fields"]}
