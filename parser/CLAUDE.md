# 文档解析（Document Parser）

文档解析服务，接收上传文档（PDF/Office/HTML），通过 MinerU 进行 AI 解析，返回结构化内容。

## 项目文档

- **架构文档**：`PROJECT_INDEX/architecture.md`
- **代码签名索引**：`PROJECT_INDEX/history/`（repomix 自动生成）

## 更新索引

```bash
bash update_index.sh
```

## 运行

```bash
python main.py
```

## 测试

```bash
pytest tests/ -v
```
