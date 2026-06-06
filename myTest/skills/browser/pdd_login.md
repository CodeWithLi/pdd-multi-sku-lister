# 拼多多商家后台登录 Skill

## 入口

- 首页：https://mms.pinduoduo.com/home/
- 未登录会跳转 login 页

## 流程

1. 使用店铺独立 Profile 打开首页
2. 若 URL 含 login → 切换「账号登录」→ 填用户名密码
3. 等待跳转离开 login 页（最多 30s）
4. 登录成功后保留 Context，供后续 Skill 复用

## 防检测策略（降低滑块频率，而非每次硬过）

拼多多无法做到「永远不被识别」，目标是：**少登录、像真人、稳定复用 Session**。

| 层级 | 做法 | 效果 |
|------|------|------|
| 1 | 每店铺独立 `data/profiles/{id}/user_data/`（与老项目 ChromeProfiles 隔离） | 登录一次可用数天～数周，**日常跑任务不弹滑块** |
| 2 | `browser.channel: chrome` 用本机 Chrome，不用自带 Chromium | 浏览器指纹更接近日常办公 |
| 3 | `headless: false`，禁用 `--enable-automation`，注入 stealth 脚本 | 隐藏 `navigator.webdriver` 等标记 |
| 4 | 登录用 `human.py`：随机延迟、逐字输入、鼠标移动后点击 | 避免 `fill()` 瞬填被行为风控命中 |
| 5 | 固定 IP、固定机器、控制频率（如每店每天 1～2 次批量上架） | 异常登录/高频操作更容易触发滑块 |

## 滑块验证码（拼图）

仅在 **Session 过期 / 新设备 / 风控升级** 时出现。此时：

1. 运行 `python scripts/manual_login.py store_B`（或执行任务时盯着窗口）
2. **手动拖一次滑块**（约 10 秒）
3. Profile 更新后，后续自动化继续免登录

**不建议**自写 OpenCV 自动拖滑块或接打码平台：拼多多拼图带轨迹检测，容易被二次风控甚至封号。

## 异常

- 滑块超时 → 重新运行 `manual_login.py`
- Session 过期 → 偶发需再拖一次滑块，属于正常情况
- 频繁弹滑块 → 检查是否换了 IP/机器、是否 headless、是否 channel 未设 chrome
