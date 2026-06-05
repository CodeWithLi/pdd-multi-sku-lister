import re
import requests

# ================= 配置区域 =================
BASE_URL = "https://m.plivo.com.cn:8003/api/v2"  # 或者使用 http://113.44.151.255:8002/api/v2
API_KEY = ""  # 替换为你的真实 API Key [cite: 5]
TARGET_PHONE = "13800138000"  # 想要接收验证码的手机号（设备号码）
# ============================================


def get_latest_captcha(phone_number):
    """从指定手机号的设备中，获取最新的短信验证码"""
    # 1. 拼接接口 URL
    # 格式为: BaseURL/{apikey}/sms-list [cite: 5, 66]
    url = f"{BASE_URL}/{API_KEY}/sms-list"

    # 2. 设置请求参数 [cite: 67]
    # limit=5 表示只看最近的5条，避免数据太多；body 传入“验证码”进行模糊匹配过滤
    params = {
        "body": "验证码",  # 模糊匹配短信内容
        "limit": 5,  # 返回数量
        "offset": 0,  # 偏移量
    }

    print(f"正在请求接口查询手机号 [{phone_number}] 的短信...")

    try:
        response = requests.get(url, params=params, timeout=10)
        # 检查 HTTP 状态码
        if response.status_code != 200:
            print(f"接口请求失败，HTTP 状态码: {response.status_code}")
            return None

        res_json = response.json()

        # 3. 校验接口返回状态 [cite: 74]
        if not res_json.get("success"):  # [cite: 8, 74]
            print(f"接口返回错误: {res_json.get('message')}")  # [cite: 10]
            return None

        sms_list = res_json.get("data", [])  # [cite: 76]
        if not sms_list:
            print("没有找到匹配的短信。")
            return None

        # 4. 遍历短信列表，寻找属于目标手机号的最新一条短信
        # 注：如果你的一个 apikey 绑定了多个设备，可以通过 udid 区分；
        # 如果单设备单号码，直接取第一条即可。这里我们加上设备号码的匹配逻辑保护。
        for sms in sms_list:
            sms_body = sms.get("body", "")  # 短信内容 [cite: 93]
            created_at = sms.get("createdAt", "")  # 接收时间 [cite: 93]

            print(f"\n[找到短信] 时间: {created_at} | 内容: {sms_body}")  # [cite: 93]

            # 5. 正则表达式提取 4-6 位数字验证码
            captcha_match = re.search(r"\d{4,6}\b", sms_body)
            if captcha_match:
                captcha = captcha_match.group()
                print(f"🎉 成功提取验证码: {captcha}")
                return captcha

        print("未能从短信内容中解析出数字验证码。")
        return None

    except requests.exceptions.RequestException as e:
        print(f"网络请求发生异常: {e}")
        return None


if __name__ == "__main__":
    # 运行测试
    captcha_code = get_latest_captcha(TARGET_PHONE) 

    if captcha_code:
        print(f"\n最终测试结果: 拿到了验证码 [{captcha_code}]，可以填入浏览器了。")
    else:
        print("\n最终测试结果: 未能获取到验证码。")