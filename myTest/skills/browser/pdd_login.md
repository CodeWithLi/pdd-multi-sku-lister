# 拼多多商家后台登录 Skill

## 入口

- 首页：https://mms.pinduoduo.com/home/
- 未登录会跳转 login 页

## 流程

1. 使用店铺独立 Profile 打开首页
2. 若 URL 含 login → 切换「账号登录」→ 填用户名密码
3. 等待跳转离开 login 页（最多 30s）
4. 登录成功后保留 Context，供后续 Skill 复用

## 异常

- 出现滑块/验证码 → 标记 `needs_human`，暂停 Graph 等待人工处理
- Session 过期 → 重新登录，最多重试 2 次
