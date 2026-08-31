# 四张表的字段结构定义。
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
#   date        日期（自动填充，不可手填）
#   checkbox    是否勾选
#   user        创建人 / 负责人（自动取当前登录用户）

TABLE_SCHEMAS = {
    "sku": {
        "label": "1. Etsy-SKU管理表",
        "order": 1,
        "fields": [
            {"key": "sku_code", "label": "SKU编号", "type": "text", "required": True},
            {"key": "category", "label": "商品类目", "type": "multiselect",
             "options": ["数字产品", "油画", "数字印刷画", "数字油画"]},
            {"key": "competitor_link", "label": "竞品链接", "type": "url"},
            {"key": "design_highlight", "label": "设计亮点", "type": "text"},
            {"key": "dev_stage", "label": "开发阶段", "type": "select",
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
        "fields": [
            {"key": "task_code", "label": "任务编号", "type": "text", "required": True},
            {"key": "related_sku", "label": "关联SKU", "type": "text"},
            {"key": "status", "label": "制作状态", "type": "select",
             "options": ["待制作", "制作中", "已完成"]},
            {"key": "maker", "label": "制作人", "type": "text"},
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
        "fields": [
            {"key": "task_code", "label": "任务编号", "type": "text", "required": True},
            {"key": "related_sku", "label": "关联SKU", "type": "text"},
            {"key": "status", "label": "制作状态", "type": "select",
             "options": ["待制作", "制作中", "已完成"]},
            {"key": "priority", "label": "优先级", "type": "rating"},
            {"key": "note", "label": "备注", "type": "long_text"},
            {"key": "competitor_link", "label": "竞品链接参考", "type": "url"},
            {"key": "maker", "label": "制作人", "type": "text"},
            {"key": "finished_at", "label": "完成时间", "type": "date"},
            {"key": "created_at", "label": "创建时间", "type": "date", "auto": True},
            {"key": "attachment", "label": "成品附件链接", "type": "url"},
        ],
    },
    "pending_listing": {
        "label": "4. Etsy待上架表",
        "order": 4,
        "fields": [
            {"key": "task_code", "label": "待上架任务编号", "type": "text", "required": True},
            {"key": "note", "label": "任务备注", "type": "long_text"},
            {"key": "finished_at", "label": "完成时间", "type": "date"},
            {"key": "created_at", "label": "创建时间", "type": "date", "auto": True},
            {"key": "is_listed", "label": "是否已上架", "type": "checkbox"},
            {"key": "shop_owner", "label": "店铺负责人", "type": "text"},
            {"key": "related_sku", "label": "关联SKU", "type": "text"},
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
