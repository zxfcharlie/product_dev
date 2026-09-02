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
#   auto            完全由系统生成，编辑/新建表单里都不出现（如创建时间、创建人、SKU开发阶段）
#   auto_on_create  新建时不出现（由自动化规则填入），但编辑时可以手动修改（如制作人/店铺负责人）
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
             "options": [], "dynamic_options": "category_config"},
            {"key": "competitor_link", "label": "竞品链接", "type": "url"},
            {"key": "design_highlight", "label": "设计亮点", "type": "text"},
            {"key": "dev_stage", "label": "开发阶段", "type": "select", "auto": True,
             "options": ["SKU创建", "AI主图制作中", "套图制作中", "待上架", "已上架"]},
            {"key": "est_sales", "label": "eranks预估销量", "type": "number"},
            {"key": "listing_time", "label": "listing时间", "type": "text"},
            {"key": "market_heat", "label": "市场热度", "type": "rating"},
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
            {"key": "assignees", "label": "负责人（按顺序，英文逗号分隔）", "type": "text"},
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
            {"key": "category", "label": "所属品类", "type": "text"},
        ],
    },
    "category_config": {
        "label": "⚙ 品类负责人配置表",
        "order": 12,
        "group": "config",
        "fields": [
            {"key": "level1_category", "label": "一级类目", "type": "text", "required": True},
            {"key": "level2_category", "label": "二级类目", "type": "text"},
            {"key": "responsible_person", "label": "负责人", "type": "text"},
        ],
    },
}


def get_schema(table_key: str):
    return TABLE_SCHEMAS.get(table_key)


def field_map(table_key: str):
    schema = get_schema(table_key)
    if not schema:
        return {}
    return {f["key"]: f for f in schema["fields"]}
