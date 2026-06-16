@echo off
REM 飞书联调：同时启动测试 API(8001) 与测试前端(5174)
REM 用法：在 myTest 根目录执行 scripts\start_feishu_test.bat

cd /d "%~dp0.."

echo [1/2] 启动飞书测试 API :8001 ...
start "feishu-test-api" cmd /k "python scripts/feishu_test_server.py --host 127.0.0.1 --port 8001"

timeout /t 2 /nobreak >nul

echo [2/2] 启动飞书测试前端 :5174 ...
cd frontend-feishu-test
if not exist node_modules (
  echo 正在 npm install ...
  call npm install --registry https://registry.npmmirror.com
)
start "feishu-test-ui" cmd /k "npm run dev"

echo.
echo 打开浏览器: http://127.0.0.1:5174
echo API 文档:   http://127.0.0.1:8001/docs
echo 请先配置 config\feishu.yaml（可复制 feishu.example.yaml）
pause
