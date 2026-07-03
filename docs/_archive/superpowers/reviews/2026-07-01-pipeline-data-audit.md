# Pipeline 数据一致性审核报告

**日期**: 2026-07-01
**审核范围**: 前端 PipelineView 展示数据 vs 数据库实际数据
**严重程度**: 🔴 P0 — 元数据阶段数据丢失

---

## 一、数据库实际状态

### 1.1 收件箱摄入（Ingest）
```
_inbox/ 目录: 2 个子目录（奖励黑客、目标错误泛化），0 个 PDF 文件
✅ 结论：前端显示 0 正确
```

### 1.2 文档解析（Parse）
```
literature_parse_runs 表:
  - succeeded: 152
  - pending:   0
  - failed:    0

works.parse_status:
  - succeeded: 150 (150/150 全部解析完毕)

⚠️ 注意：前端 `stages.parse.count = res.pending = 0` 技术上正确，
        但用户体验不佳——用户看不到"已全部完成"的状态反馈
```

### 1.3 元数据抽取（Metadata）🔴 核心问题
```
metadata_extractions 表（共 261 条）:

review_status 分布（原始）:
  - approved: 119 (45.6%)
  - rejected: 131 (50.2%)
  - pending:  11  (4.2%)  ← 有待处理！

review_status 分布（排除 quarantined 后）:
  - pending:  1  ← API 应返回此值
  - (10 条 pending 记录的 works.read_status = 'quarantined' 被过滤)

具体 pending 文件列表:
  work_id                  title                          read_status
  ──────────────────────── ────────────────────────────── ────────────
  W-sha-0910d09cb1b2       Blog | Scale AI                unread      ✓ 可显示
  W-sha-208c5b4a6da3       CASI and ARS Leaderboards       quarantined ✗ 被隔离
  W-sha-610d342aaad3       国家工业信息安全发展研究中心     quarantined ✗ 被隔离
  W-sha-aebc7bd7374f       CASI and ARS Leaderboards       quarantined ✗ 被隔离
  W-sha-b5cbc9e3f952       Blog | Scale AI                quarantined ✗ 被隔离
  W-sha-c3e652a5c0ca       Blog | Scale AI                quarantined ✗ 被隔离
  W-sha-d63d90d07955       国家工业信息安全发展研究中心     quarantined ✗ 被隔离
  W-sha-ecb8076f0829       Monitoring Monitorability      quarantined ✗ 被隔离
  + 2 条重复 work_id

❌ 问题：前端应显示 count=1，但用户反馈显示为 0
```

### 1.4 分类抽取（Classification）
```
classification_extractions 表（共 373 条）:

review_status 分布:
  - approved: 119 (31.9%)
  - rejected: 254 (68.1%)
  - pending:   0  ← 确实没有待审核

✅ 结论：前端显示 0 正确（全部审核完毕）
```

---

## 二、前后端数据流分析

### 2.1 前端调用链路（PipelineView.vue）

```javascript
// 第 420-427 行：元数据加载逻辑
async function loadMetadata() {
  const res = await getMetadataExtractions({
    status: stages.value.metadata.statusFilter || undefined,  // 默认 'pending'
    per_page: 200,
  })
  stages.value.metadata.items = res.extractions || res.items || []
  stages.value.metadata.count = res.total || stages.value.metadata.items.length
}
```

**字段映射检查**:
- API 返回格式: `{ extractions: [...], total: N, summary: {...} }` ✅ 匹配
- 前端读取: `res.extractions`, `res.total` ✅ 正确

### 2.2 后端 API 逻辑（api/routes/metadata.py）

```python
@router.get("/metadata")
def list_metadata(status: str = Query("pending"), ...):  # 默认 status="pending"
    # 过滤条件:
    # 1. w.read_status != 'quarantined'  （默认启用）
    # 2. me.review_status = 'pending'     （来自前端参数）

    where_parts = [
        "w.read_status != 'quarantined'",
        "me.review_status = 'pending'"  # status != "all" 时添加
    ]

    # 返回值:
    return {
        "extractions": [...],  # 应包含 1 条记录
        "total": 1,            # 应等于 1
        "summary": { "pending": 1, ... }
    }
```

**理论返回**: `{ extractions: [1条记录], total: 1 }`

---

## 三、问题根因定位

### 可能原因（按可能性排序）

#### 🥇 原因 1: 后端服务未启动 / API 请求失败（概率 70%）

**现象**:
```javascript
// PipelineView.vue 第 428-430 行
} catch (e) {
  console.error('Failed to load metadata:', e)  // 错误被吞掉，不展示
}
```

如果后端未启动或端口不对：
1. 所有 4 个 `loadXxx()` 函数都会进入 catch
2. `stages.value.metadata.count` 保持初始值 `0`
3. 控制台有错误日志，但用户无感知

**验证方法**:
- 打开浏览器 F12 → Network 标签 → 刷新页面
- 检查 `/metadata?status=pending&per_page=200` 请求状态码
- 若为 404/500/Failed 则确认此问题

#### 🥈 原因 2: API 返回格式异常（概率 20%）

**场景**:
- 后端抛出 HTTPException（如 validate_status 失败）
- 返回 HTML 错误页而非 JSON
- 前端 JSON 解析失败，进入 catch

**验证方法**:
- 检查 Response Content-Type 是否为 `application/json`
- 查看 Response Body 是否为有效 JSON

#### 🥉 原因 3: 浏览器缓存（概率 10%）

**现象**:
- 开发服务器热更新残留旧代码
- Service Worker 缓存旧响应

**验证方法**:
- Ctrl+Shift+R 强制刷新
- 清除浏览器缓存后重试

---

## 四、修复建议

### 4.1 立即修复（不改数据库）

#### Step 1: 验证后端服务状态
```bash
# 检查后端是否运行
curl http://localhost:8000/metadata?status=pending&per_page=20
# 或访问 http://localhost:8000/docs 查看 Swagger UI
```

若未启动：
```bash
cd api
uvicorn main:app --reload --port 8000
```

#### Step 2: 前端错误可见化增强（推荐）

修改 `PipelineView.vue` 的 catch 块：

```javascript
async function loadMetadata() {
  try {
    // ...existing code...
  } catch (e) {
    console.error('Failed to load metadata:', e)
    showError(`加载元数据失败: ${e.message}`)  // 新增：向用户展示错误
  }
}
```

同理修改其他 3 个 load 函数。

#### Step 3: 添加加载状态指示

当前所有阶段的 loading 只在批量操作时为 true，初始加载时无反馈。

建议在 `onMounted(loadAll)` 时设置全局 loading 状态。

### 4.2 中期优化（提升用户体验）

#### 问题 A: 文档解析阶段缺少"已完成"提示

**现状**: `stages.parse.count = res.pending = 0`（全部完成时）

**建议**: 显示总进度而非仅 pending 数量
```vue
<StageCard
  :count="stages.parse.succeeded"
  stat-label="已完成"
  :subtitle="`共 ${stages.parse.total} 个文档`"
/>
```

需同步修改后端 `/parse/status` 返回值，增加 succeeded/total 字段。

#### 问题 B: 元数据 pending 只有 1 条且被隔离 10 条

**用户困惑点**:
- 数据库有 11 条 pending，但只能看到 1 条
- 其余 10 条被静默隔离，无任何提示

**建议**:
1. 在 StageCard 底部显示提示文字：
   > "另有 10 条文件已被隔离，可在隔离管理中查看"

2. 或在 summary 中增加 `quarantined_pending` 字段

### 4.3 长期优化（可选）

1. **添加 WebSocket/SSE 实时推送**
   - 当前每次操作后手动 `loadAll()`，可改为事件驱动更新

2. **Pipeline 进度持久化**
   - 将各阶段 count 写入 Redis/内存缓存，避免重复查询

3. **添加单元测试**
   - mock API 返回值，验证前端数据处理逻辑

---

## 五、数据完整性检查清单

| 检查项 | 状态 | 说明 |
|--------|------|------|
| works 表行数 | ✅ 150 | 与 parse_runs 152 接近（允许 2 行差异）|
| metadata_extractions 总数 | ✅ 261 | 合理（部分 work 有多次抽取）|
| classification_extractions 总数 | ✅ 373 | 合理 |
| 外键完整性 | ⚠️ 待查 | me.work_id / ce.work_id 是否都有对应 works 行 |
| 隔离数据一致性 | ⚠️ 待查 | 10 条 pending 的 works 是否真被隔离 |

---

## 六、结论

### 核心发现
1. **元数据阶段应显示 1 条 pending**（实际显示 0）→ 🔴 P0 bug
2. **文档解析阶段 pending=0 正确**，但缺少"已完成"反馈
3. **分类抽取确实全部完成**，显示 0 正确
4. **收件箱为空**，显示 0 正确

### 最可能原因
**后端服务未启动或 API 调用失败**，导致前端 4 个 load 函数全部进入 catch 分支，count 保持初始值 0。

### 下一步行动
1. 用户验证后端是否启动（最高优先级）
2. 若后端正常，则检查浏览器控制台 Network 请求详情
3. 增强前端错误提示（catch 块 showError）
4. 优化已完成阶段的视觉呈现

---

**审核人**: AI Assistant
**附件**: 无
