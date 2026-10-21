# 安装、启动与故障处理

## 环境

Node.js 22.12+；Python 3.11+（本次机器是 Python 3.14）；支持摄像头的现代 Chrome/Edge。仅本机 localhost，普通笔记本性能需要实测。

Windows 从 README 的两终端命令启动。macOS/Linux 把 `.venv\Scripts\python.exe` 换成 `.venv/bin/python`。后端锁文件是本次实测版本；若其他平台需变更依赖，记录并更新测试。

## 摄像头资产

在 frontend 执行 `npm ci`、`npm run prepare:models`，生成 `/public/models/pose_landmarker_lite.task`、manifest 及 `/public/wasm` 运行文件。脚本固定模型 URL 与 npm 包版本，记录 SHA-256，权重不入 Git。没有可达下载网络时在有网络的设备准备后复制这些文件夹，并校验 manifest。许可复核见 DEPENDENCIES。

摄像头失败：检查浏览器权限、其他程序占用、是否用 localhost 安全上下文；模型失败检查 `/models` 和 `/wasm` 请求是否返回文件而不是 HTML。当前模型 Worker CPU 基线可能较慢，不保证所有浏览器均通过。

## 可选同机 LLM

安装官方 llama.cpp，选择并核对中文模型/量化权重。在本机回环启动兼容 `/v1/chat/completions` 的服务（常用端口 8080）。启动后端前设置：

```powershell
$env:LOCAL_LLM_ENABLED = 'true'
$env:LOCAL_LLM_URL = 'http://127.0.0.1:8080'
```

`.env.example` 只是示例，本代码不会自动加载 `.env`。网页复盘点击“查看解释”。未启用直接用规则文本；超时或服务异常降级。当前未捆绑或自动启动 LLM，不宣称已经测过具体权重。只允许回环 URL，禁止凭据和重定向。

## 常见问题

10/21 模式：默认浏览器规则；需要后端请打开 `?runtime=backend`。只有该模式会请求 /api；后端异常会显示错误，不会自动切换成浏览器结果。严格资源模式默认启用；模型未准备会报错，不自动下载 CDN。可选 `&assets=online` 明确允许外部资源，不属于严格离线。

- 网页服务待启动：检查 8000 服务和 Vite proxy，后端 `/api/health`。
- 端口占用：确认不是队友已有服务，选其他端口时同步 Vite 代理和 CORS。
- 计划不调整：观察不足（覆盖率 <0.6 或活动 <10s）时保持，查看 trace；阈值是待验证规则。
- 重启后不能确认旧报告：待确认状态只在进程内，重新训练，不恢复执行旧提案。
- 模型下载被代理阻断：配置所在终端的网络代理；不要把代理凭据写入仓库。
- 单服务展示：准备模型后 `npm run build`，重启后端，打开 8000；后端在启动时检查 dist 是否存在。
- `vite preview`：只作静态预览；完整 API 联调请用 dev 或后端单服务。
- 公网演示：启用 GitHub Pages（Actions 源），不需要自购域名或云主机。静态页在后端不可用时自动降级为浏览器本地教练。不要把无认证的 FastAPI 直接映射到公网。

## 构建展示文档

```powershell
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements.txt
.\.venv\Scripts\python.exe scripts/export_docs.py
```

`docs/展示文档.html` 是无外部依赖的独立文档，下载后双击查看，也可浏览器打印为 PDF。Markdown 为团队维护的源版本。源码 Mermaid 在 GitHub 可渲染，展示版保留文本图与独立结构说明。
