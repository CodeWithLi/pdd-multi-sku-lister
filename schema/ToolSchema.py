# 定义教导 AI 如何使用的“工具说明书”
UPLOAD_PRODUCT_TOOL = {
    "type": "function",
    "function": {
        "name": "upload_pdd_product",
        "description": "自动将指定颜色的商品上架到对应的拼多多商家后台",
        "parameters": {
            "type": "object",
            "properties": {
                "category_keyword": {
                    "type": "string",
                    "description": "商品的类目关键词，例如：其它文具、笔袋、文具盒"
                },
                "title": {
                    "type": "string",
                    "description": "商品标题，要求包含描述加规格，最多30个汉字"
                },
                "group_price": {
                    "type": "string",
                    "description": "拼单价格，单位元，例如：19.9"
                },
                "single_price": {
                    "type": "string",
                    "description": "单买价格，单位元，例如：29.9"
                },
                "inventory": {
                    "type": "string",
                    "description": "上架的库存数量，默认为 99"
                }
            },
            "required": ["category_keyword", "title", "group_price", "single_price"]
        }
    }
}