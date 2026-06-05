import json
from openai import OpenAI
# 导入我们之前写好的核心业务函数
from pdd_auto.listing.runner import process_single_account
from pdd_auto.config import load_config
from schema.ToolSchema import UPLOAD_PRODUCT_TOOL
# 初始化千问客户端 (此处以通义千问官方API或自建中转为例)
client = OpenAI(
    api_key="sk-xxxxxxxx",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"  # 千问的OpenAI兼容端点
)


def ask_ai_agent(user_instruction):
    print(f"\n[AI Agent] 收到用户指令: '{user_instruction}'")

    # 1. 引导 AI 分析指令
    messages = [{"role": "user", "content": user_instruction}]

    response = client.chat.completions.create(
        model="qwen-turbo",  # 或 qwen-max, qwen2.5 等最新模型
        messages=messages,
        tools=[UPLOAD_PRODUCT_TOOL],  # 把说明书塞给大模型
        tool_choice="auto"
    )

    response_message = response.choices[0].message

    # 2. 检查 AI 是否决定调用我们的“上架工具”
    if response_message.tool_calls:
        tool_call = response_message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)

        print(" [AI Agent] 🎯 成功识别发品意图！大模型提取到的参数如下：")
        print(json.dumps(args, indent=2, ensure_ascii=False))

        # 3. 补全程序所需要的衍生参数 (比如自动生成编码)
        product_info = {
            "category_keyword": args.get("category_keyword"),
            "title": args.get("title"),
            "inventory": args.get("inventory", "999"),  # 没给就给个默认值
            "group_price": args.get("group_price"),
            "single_price": args.get("single_price"),
            "sku_code": "AI-SKU",
            "product_code": "AI-ITEM"
        }

        # 4. 读取账户配置，开始流水线发品
        config_data = load_config()
        accounts_list = config_data.get('accounts', [])

        # 依次为开启的店铺执行上架
        for account in accounts_list:
            if account.get('enabled'):
                # 完美复用之前写好的浏览器自动化函数！
                process_single_account(account, product_info)

    else:
        # 如果用户只是和 AI 聊天，没有触发上架指令
        print(f" [AI Agent] 💬 AI 回复: {response_message.content}")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        user_input = sys.argv[1]
    else:
        user_input = "帮我上架一款商品，类目是其它文具。标题就叫『精选文具盒大容量文具袋』，拼单价设为25块8，单买价35块。"
    ask_ai_agent(user_input)