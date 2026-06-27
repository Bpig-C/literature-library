#!/bin/bash
# 更新项目索引
echo "=== 更新项目索引 ==="
echo "运行 repomix..."

ts=$(date +"%Y-%m-%d_%H-%M-%S")
sed -i.bak "s/{datetime}/$ts/" repomix.config.json && rm -f repomix.config.json.bak
npx repomix@latest --config repomix.config.json --compress
sed -i.bak "s/$ts/{datetime}/" repomix.config.json && rm -f repomix.config.json.bak

echo ""
echo "✅ 索引已更新"
echo ""
echo "=== 检测变更 ==="

latest=$(ls -t PROJECT_INDEX/history/*.md 2>/dev/null | head -1)
previous=$(ls -t PROJECT_INDEX/history/*.md 2>/dev/null | head -2 | tail -1)

if [ -z "$previous" ]; then
    echo "这是首次生成索引，没有历史版本可比对"
    echo "最新索引: $latest"
elif [ "$latest" = "$previous" ]; then
    echo "只有一个历史版本，没有变更"
else
    echo "比对: $previous"
    echo "  vs: $latest"
    echo ""
    diff -u "$previous" "$latest" > PROJECT_INDEX/latest_changes.diff
    added=$(grep -c "^+[^+]" PROJECT_INDEX/latest_changes.diff 2>/dev/null; true)
    removed=$(grep -c "^-[^-]" PROJECT_INDEX/latest_changes.diff 2>/dev/null; true)
    echo "变更统计:"
    echo "  新增: $added 行"
    echo "  删除: $removed 行"
    echo ""
    echo "详细变更: PROJECT_INDEX/latest_changes.diff"
fi

echo ""
echo "提示："
echo "- 架构文档: PROJECT_INDEX/architecture.md（需手动维护）"
echo "- 代码签名索引: PROJECT_INDEX/history/（自动生成）"
