# 蒸汽杀菌致死量 F₀ 复核

常温乳品批次完成蒸汽杀菌后，质检员在此录入釜内探头的时间—温度采样，系统按梯形法积分复核致死量 F₀，达到 **3.00 min** 即放行。

## 业务规则

- 每个采样点的致死速率：`rate = 10^((T - 121.1) / 10)`（T 为 °C）。
- 相邻两点按梯形法积分：`段贡献 = (rate₁ + rate₂) / 2 × Δt秒 / 60`（分钟）。
- 各段以**未舍入**的值累加，最终 F₀ **四舍五入保留两位小数**；≥ 3.00 min 判定放行。
- 采样约束：至少 2 个点；时间从 0 秒起的整数秒且严格递增；相邻间隔 ≤ 60 秒；温度为 100.0–140.0 °C 的有限数。
- 任一行非法 → 整次请求失败（HTTP 422），响应指明行号与字段，前端同时清除旧结论。
- 不足量批次显示距门槛的差额；达标批次展示逐段贡献，可逐段复算放行值。

### 双探头保守复核

同一批次两支探头的采样时刻不完全一致时，质检员按**每一时刻较低的致死速率**形成保守结论，而不是简单取两份总 F₀ 的较小值。

- 两支探头各自从 0 秒开始、结束于**同一秒**，并分别遵守上述全部时间/温度/间隔校验（问题按探头 + 行号定位）。
- 后端取两组采样时刻的**并集**，在其上按原梯形法隐含的**分段线性**口径插值两条致死速率线。
- 若两条速率线在区间内部交换高低，则在**交点处拆段**后积分下包络；每个保守段返回来源探头（`probeA` / `probeB` / `both` 重合）、两探头各自速率与段贡献。
- 响应同时给出两探头各自总量与**保守总量**；放行只用**未舍入**的保守总量与 3.00 min 门槛比较（`conservativeF0` 仅为四舍五入展示口径）。
- 页面并列显示两支探头的速率曲线（含交点、按下包络来源着色）与保守段明细表，**表格与图形使用同一响应**。
- 双探头输入或请求失败只清除本次比较，不改写已经显示的单探头结论；原 `/api/lethality` 接口及其响应保持兼容。

### 三探头中位复核（可选模式）

新增第三支探头时，质检员按**任一时刻三支探头致死速率的中位值**积分 F₀，而不是先分别算三份总 F₀ 再取其中位数；后者会掩盖单支探头在局部时间段的异常。

- `/api/lethality/triple` 要求 `probeA`、`probeB`、`probeC` 三路均存在，各自遵守单探头的全部采样校验，并共同从 0 秒开始、结束于同一秒。
- 后端在三路采样时刻的并集上构造三条分段线性速率曲线，再加入任两条曲线的内部交点作为共享边界。
- 每个切出的时间段在开区间中点确定中位来源；并列中位值按固定探头顺序 **A → B → C** 裁决：两低值并列取顺序靠前者，两高值并列同样取并列者中的顺序靠前者，三线重合取 `probeA`。
- 交点恰好重合时合并为同一个共享边界；端点贴线、采样节点换序和浮点尾噪都按同一规则处理，响应不产生零时长片段。
- 每段返回来源探头、来源裁决说明、三探头起止速率、起止共享边界编号及未舍入贡献；顶层 `boundaries` 与 `segments` 是计算摘要、片段表和图表共用的唯一边界来源。
- 放行只比较未舍入的 `medianUnrounded` 与 3.00 min 门槛；`medianF0` 仅为两位小数展示口径，展示舍入不得改变放行判断。
- 第三路缺样、时间域不相交/结束秒不一致或任一路数据非法时，本次三探头请求返回 422；页面会保留上一份有效的三探头报告。原单、双探头接口和响应语义不变。

## 快速开始（Docker Compose）

```bash
docker compose up --build -d        # 启动 api + web
docker compose run --rm verify      # 一次性验收服务：黑盒检查全部通过则退出码为 0
```

浏览器打开 <http://localhost:8080>。Web 宿主端口可用环境变量覆盖：

```bash
WEB_PORT=9000 docker compose up --build -d   # 改为 http://localhost:9000
```

架构：`web`（nginx，伺服 React 构建产物并把 `/api` 同源代理到 `api`）→ `api`（FastAPI，致死量积分与校验）→ `verify`（一次性验收容器，跑完即退出）。

## 故障排查

- **web 一直不健康、verify 与首页无法启动**：旧版 `frontend/nginx.conf` 在 `proxy_pass` 中使用字面主机名，nginx 只在启动时解析一次 `api`；若此刻 `api` 尚未注册到 Docker 网络 DNS（启动顺序、容器重启、旧版 compose 忽略健康条件），nginx 会以 `host not found in upstream` 退出，web 容器随之不健康，依赖它的 verify 也被连锁阻塞。当前配置已改为 `resolver 127.0.0.11` + 变量式 `proxy_pass`，在请求时解析上游：nginx 不再因 `api` 未就绪而退出，`api` 恢复后 `/api` 自动可用，静态首页始终可访问。
- 查看健康检查失败原因：`docker compose ps` 后 `docker inspect --format '{{json .State.Health}}' <容器>`。
- 手动复跑验收：`docker compose run --rm verify`（verify 自身会等待服务就绪，最长 120 秒）。

## 测试

| 层 | 工具 | 运行 |
| --- | --- | --- |
| 计算边界 | pytest | `cd backend && pip install -r requirements-dev.txt && python -m pytest` |
| 录入交互 | Vitest | `cd frontend && npm ci && npm test` |
| 前后端联调 | Playwright | `docker compose up -d --build && cd frontend && npx playwright install chromium && npm run e2e` |

Playwright 也可整体容器化运行（无需本机装浏览器）：

```bash
docker compose --profile e2e run --rm e2e
```

联调测试默认打向 `http://localhost:8080`，可用 `BASE_URL` 或 `WEB_PORT` 环境变量覆盖。所有测试均走真实 HTTP 与真实计算，无固定结果或假接口。

## API

### `POST /api/lethality`

请求：

```json
{
  "points": [
    { "time": 0,   "temperature": 121.1 },
    { "time": 60,  "temperature": 121.1 },
    { "time": 120, "temperature": 121.1 },
    { "time": 180, "temperature": 121.1 }
  ]
}
```

达标响应（200）：

```json
{
  "f0": 3.0,
  "threshold": 3.0,
  "passed": true,
  "shortfall": null,
  "segments": [
    {
      "index": 1,
      "startTime": 0,
      "endTime": 60,
      "startTemperature": 121.1,
      "endTemperature": 121.1,
      "startRate": 1.0,
      "endRate": 1.0,
      "durationSeconds": 60,
      "contribution": 1.0
    }
  ]
}
```

校验失败响应（422，`row` 为 1-based 行号，`null` 表示整体问题）：

```json
{
  "detail": {
    "message": "采样数据校验失败，整次请求已拒绝",
    "errors": [
      { "row": 2, "field": "temperature", "message": "温度须在 100.0 至 140.0 °C 之间" }
    ]
  }
}
```

### `GET /api/health`

返回 `{"status": "ok"}`。

### `POST /api/lethality/dual`

双探头保守复核。请求体（两支探头各自携带 `points`，校验规则同上，问题多一个 `probe` 字段）：

```json
{
  "probeA": {
    "points": [
      { "time": 0, "temperature": 121.1 },
      { "time": 30, "temperature": 123.0 },
      { "time": 60, "temperature": 121.1 }
    ]
  },
  "probeB": {
    "points": [
      { "time": 0, "temperature": 123.0 },
      { "time": 60, "temperature": 123.0 }
    ]
  }
}
```

响应（200，节选）：

```json
{
  "threshold": 3.0,
  "probeA": { "probe": "probeA", "points": [{ "time": 0, "temperature": 121.1, "rate": 1.0 }],
              "totalUnrounded": 1.23, "f0": 1.23 },
  "probeB": { "...": "..." },
  "probeATotalUnrounded": 1.23,
  "probeBTotalUnrounded": 2.00,
  "conservativeUnrounded": 1.18,
  "conservativeF0": 1.18,
  "passed": false,
  "shortfall": 1.82,
  "segments": [
    {
      "index": 1,
      "startTime": 0.0, "endTime": 22.5, "durationSeconds": 22.5,
      "source": "probeA",
      "startRate": 1.0, "endRate": 1.6,
      "probeAStartRate": 1.0, "probeAEndRate": 1.6,
      "probeBStartRate": 1.5, "probeBEndRate": 1.6,
      "contribution": 0.4875
    }
  ]
}
```

- `source` 为 `probeA` / `probeB` / `both`（两线重合）；交点拆段后相邻段在交点处速率相等。
- 段 `startTime/endTime` 为交点时可以是小数秒（采样时刻本身仍是整数秒）。
- 跨探头整体问题（如两支探头结束秒不一致）：`{"row": null, "field": "probe", "probe": null, ...}`；单支探头的问题带 `"probe": "probeA" | "probeB"`。

### `POST /api/lethality/triple`

三探头逐刻中位值复核。请求体在双探头基础上增加 `probeC`：

```json
{
  "probeA": { "points": [{ "time": 0, "temperature": 121.1 }] },
  "probeB": { "points": [{ "time": 0, "temperature": 121.2 }] },
  "probeC": { "points": [{ "time": 0, "temperature": 121.3 }] }
}
```

响应关键字段：

```json
{
  "mode": "triple",
  "probeA": { "probe": "probeA", "points": [], "totalUnrounded": 0.0, "f0": 0.0 },
  "probeB": { "...": "..." },
  "probeC": { "...": "..." },
  "medianUnrounded": 2.875,
  "medianF0": 2.88,
  "passed": false,
  "shortfall": 0.125,
  "boundaries": [
    {
      "index": 1,
      "time": 0.0,
      "type": "sample",
      "crossingPairs": [],
      "probeARate": 1.0,
      "probeBRate": 5.0,
      "probeCRate": 2.0,
      "medianRate": 2.0,
      "medianSource": "probeC",
      "reason": "采样节点……",
      "medianReason": "探头C速率在三支探头中唯一排第 2，贡献中位值"
    }
  ],
  "segments": [
    {
      "index": 1,
      "startBoundaryIndex": 1,
      "endBoundaryIndex": 2,
      "startTime": 0.0,
      "endTime": 22.5,
      "source": "probeC",
      "sourceReason": "探头C速率在三支探头中唯一排第 2，贡献中位值",
      "probeAStartRate": 1.0,
      "probeAEndRate": 2.5,
      "probeBStartRate": 5.0,
      "probeBEndRate": 3.5,
      "probeCStartRate": 2.0,
      "probeCEndRate": 3.5,
      "contribution": 1.03125
    }
  ]
}
```

- `boundaries[].type` 为 `sample`（采样节点）或 `crossing`（内部曲线交点；多个线对交点重合时 `crossingPairs` 同时列出）。
- 片段的 `startTime/endTime` 必须分别等于其 `startBoundaryIndex/endBoundaryIndex` 指向的边界时间；图表和表格均不得另行构造边界。
- 校验错误仍使用统一 422 结构；第三路问题带 `"probe": "probeC"`，共同时间域问题为 `row: null`、`field: "probe"`。

## 本地开发

```bash
cd backend && pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # http://localhost:8000

cd frontend && npm ci && npm run dev   # http://localhost:5173（/api 已代理到 8000）
```
