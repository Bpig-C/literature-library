#!/bin/bash
# 初始化项目索引
# 不带参数运行：扫描文件结构，供配置 ignore 规则使用
# 带 --run 参数运行：正式生成索引并检查配置

echo "=== 初始化项目索引 ==="
echo "创建目录结构..."
mkdir -p PROJECT_INDEX/history

echo ""
echo "=== 项目文件结构扫描 ==="
echo "（供配置 repomix.config.json 的 ignore 规则使用）"
echo ""

find . \
  -not -path '*/.*' \
  -not -path '*/node_modules/*' \
  -not -path '*/PROJECT_INDEX/*' \
  -not -path '*/__pycache__/*' \
  -not -path '*/venv/*' \
  -not -path '*/.venv/*' \
  -not -path '*/env/*' \
  -not -path '*/dist/*' \
  -not -path '*/build/*' \
  -not -path '*/target/*' \
  -not -path '*/vendor/*' \
  -type f | sort

echo ""
echo "--- 文件类型统计 ---"
find . \
  -not -path '*/.*' \
  -not -path '*/node_modules/*' \
  -not -path '*/PROJECT_INDEX/*' \
  -not -path '*/__pycache__/*' \
  -not -path '*/venv/*' \
  -not -path '*/.venv/*' \
  -not -path '*/env/*' \
  -not -path '*/dist/*' \
  -not -path '*/build/*' \
  -not -path '*/target/*' \
  -not -path '*/vendor/*' \
  -type f | sed 's/.*\.//' | sort | uniq -c | sort -rn

echo ""
echo "--- 顶层目录结构 ---"
find . -maxdepth 2 \
  -not -path '*/.*' \
  -not -path '*/node_modules/*' \
  -not -path '*/PROJECT_INDEX/*' \
  -not -path '*/__pycache__/*' \
  -not -path '*/venv/*' \
  -not -path '*/.venv/*' \
  | sort

echo ""
echo "=========================================="
echo "请根据以上文件清单配置 repomix.config.json"
echo "确认 ignore.customPatterns 覆盖了不需要的文件类型后"
echo "再继续运行: bash init_index.sh --run"
echo "=========================================="

if [ "$1" != "--run" ]; then
    exit 0
fi

if [ ! -f "repomix.config.json" ]; then
    echo "❌ 错误：repomix.config.json 不存在，请先创建配置文件"
    exit 1
fi

if ! grep -q "{datetime}" repomix.config.json; then
    echo "⚠️  警告：repomix.config.json 中未找到 {datetime} 占位符"
    echo "   filePath 应该类似: \"PROJECT_INDEX/history\\\\ProjectName_{datetime}.md\""
    echo ""
fi

echo ""
echo "=== 生成索引 ==="
ts=$(date +"%Y-%m-%d_%H-%M-%S")
sed -i.bak "s/{datetime}/$ts/" repomix.config.json && rm -f repomix.config.json.bak
npx repomix@latest --config repomix.config.json --compress
sed -i.bak "s/$ts/{datetime}/" repomix.config.json && rm -f repomix.config.json.bak

latest=$(ls -t PROJECT_INDEX/history/*.md 2>/dev/null | head -1)
if [ -z "$latest" ]; then
    echo "❌ 错误：未找到生成的索引文件"
    exit 1
fi

echo ""
echo "✅ 生成完成: $latest"
echo ""
echo "=== 配置检查 ==="
total_files=$(grep -c "^## File:" "$latest" 2>/dev/null; true)
echo "总文件数: $total_files"
echo ""
echo "文件类型分布:"
grep "^## File:" "$latest" | sed 's/.*\.//' | sort | uniq -c | sort -rn

echo ""
echo "=== 优化建议 ==="
should_ignore=""
md_count=$(grep "^## File:" "$latest" | grep -c "\.md$" 2>/dev/null; true)
[ "$md_count" -gt 0 ] && should_ignore="${should_ignore}\n  \"**/*.md\","
json_count=$(grep "^## File:" "$latest" | grep -c "\.json$" 2>/dev/null; true)
[ "$json_count" -gt 0 ] && should_ignore="${should_ignore}\n  \"**/*.json\","
log_count=$(grep "^## File:" "$latest" | grep -c "\.log$" 2>/dev/null; true)
[ "$log_count" -gt 0 ] && should_ignore="${should_ignore}\n  \"**/*.log\","
img_count=$(grep "^## File:" "$latest" | grep -cE "\.(png|jpg|jpeg|gif|svg|webp)$" 2>/dev/null; true)
[ "$img_count" -gt 0 ] && should_ignore="${should_ignore}\n  \"**/*.png\", \"**/*.jpg\", \"**/*.gif\","
data_count=$(grep "^## File:" "$latest" | grep -cE "\.(csv|xlsx|db|sqlite)$" 2>/dev/null; true)
[ "$data_count" -gt 0 ] && should_ignore="${should_ignore}\n  \"**/*.csv\", \"**/*.xlsx\", \"**/*.db\","

if [ -n "$should_ignore" ]; then
    echo "⚠️  建议在 ignore.customPatterns 中添加："
    echo -e "$should_ignore"
    echo "添加后运行: bash update_index.sh"
else
    echo "✅ 配置良好，未发现需要忽略的文件类型"
fi

echo ""
echo "=== 下一步 ==="
echo "1. 检查索引文件: less $latest"
echo "2. 创建架构文档: PROJECT_INDEX/architecture.md"
echo "3. 创建数据库文档: PROJECT_INDEX/database_schema.md（如有数据库）"
echo "4. 更新 CLAUDE.md 添加索引引用"
echo "5. 后续更新使用: bash update_index.sh"
