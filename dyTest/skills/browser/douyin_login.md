# 抖店登录 Skill

## 后台地址

- 抖店官网：https://fxg.jinritemai.com/
- 登录入口：官网右上角「登录抖店」→ `/login/common`

## 当前登录方式：手机验证码

配置 `config/settings.yaml`：

```yaml
login:
  sms_wait_seconds: 300   # 等待手动输入验证码的最长时间
  auto_send_sms: true     # 是否自动点击「发送验证码」

accounts:
  - account_id: store_A
    phone: "17708216145"
    login_mode: sms
```

## 首次登录

```bash
cd dyTest
python scripts/manual_login.py store_A
```

流程：

1. 打开 [抖店官网](https://fxg.jinritemai.com/)
2. 点击「登录抖店」
3. 自动填写手机号、点击「发送验证码」
4. **你在浏览器手动输入验证码**
5. 脚本自动勾选协议并点击「登录」
6. 登录态保存到 `data/profiles/{account_id}/user_data/`

## 后续

- `login_mode: email_password` + `username` / `password` 待实现
- 任务执行时 `ensure_login_sync` 会复用 Profile；失效时重新走验证码流程
