import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "outputs/backend-test-cases";
await fs.mkdir(outputDir, { recursive: true });

const fontFamily = "Arial";
const workbook = Workbook.create();

const summary = workbook.worksheets.add("概览");
const cases = workbook.worksheets.add("测试用例");
summary.showGridLines = false;
cases.showGridLines = false;

const headers = [
  "用例编号", "功能模块", "测试项", "用例标题", "优先级", "测试类型",
  "前置条件", "测试步骤", "输入数据", "预期结果", "关联接口/代码", "设计依据/备注", "执行结果"
];

const rows = [
  ["TC-BE-001", "系统与健康", "健康检查", "健康检查返回服务可用状态", "高", "接口测试", "后端服务已启动；数据库初始化配置可用", "1. 调用 GET /api/v1/health", "无", "HTTP 200；响应体为 {\"status\":\"ok\"}", "app/api/v1/routes/health.py", "冒烟用例；不依赖登录态", "未执行"],
  ["TC-BE-002", "用户与认证", "微信登录", "新用户首次登录自动创建账号", "高", "接口测试", "微信 code 有效；users 表不存在对应 openid", "1. Mock 微信 code2session 返回新 openid\n2. 调用 POST /api/v1/user/login", "{\"code\":\"mock_wx_code\"}", "HTTP 200；code=0；返回 token 和用户基本信息；数据库新增该 openid 用户", "app/api/v1/routes/user.py；app/services/user_service.py", "覆盖新用户创建与 JWT 返回", "未执行"],
  ["TC-BE-003", "用户与认证", "微信登录", "已注册用户登录复用既有账号", "高", "接口测试", "users 表存在 openid=existing_openid 的用户", "1. Mock code2session 返回 existing_openid\n2. 调用 POST /api/v1/user/login", "{\"code\":\"mock_wx_code\"}", "HTTP 200；返回用户 id=5、昵称、头像、total_xp；不重复插入用户", "app/services/user_service.py；backend/tests/test_user_api.py", "覆盖登录幂等性", "未执行"],
  ["TC-BE-004", "用户与认证", "登录参数校验", "空登录 code 被拒绝", "中", "接口测试", "后端服务已启动", "1. 调用 POST /api/v1/user/login\n2. 传入空 code", "{\"code\":\"\"}", "HTTP 422；Pydantic 校验失败；不调用微信接口", "app/models/user.py；app/api/v1/routes/user.py", "边界值测试", "未执行"],
  ["TC-BE-005", "用户与认证", "个人资料", "有效 token 获取用户资料和统计", "高", "接口测试", "用户 1 已存在；Mock 用户与答题统计数据", "1. 生成 user_id=1 的 JWT\n2. 调用 GET /api/v1/user/profile", "Authorization: Bearer <token>", "HTTP 200；返回 id、昵称、头像、total_xp、quiz_count、correct_count、average_accuracy", "app/api/v1/routes/user.py；app/services/user_service.py", "验证聚合统计字段", "未执行"],
  ["TC-BE-006", "用户与认证", "鉴权", "缺少 token 访问个人资料被拒绝", "高", "安全测试", "后端服务已启动；请求不带 Authorization", "1. 调用 GET /api/v1/user/profile", "无 Authorization 头", "HTTP 401；code=4010；message 为未登录或登录已过期", "app/core/auth.py；app/main.py", "验证必选鉴权依赖", "未执行"],
  ["TC-BE-007", "用户与认证", "个人资料", "更新昵称和头像成功", "中", "接口测试", "用户已登录；资料更新前状态已知", "1. 调用 PUT /api/v1/user/profile", "{\"nickname\":\"新昵称\",\"avatar_url\":\"https://example.com/a.png\"}", "HTTP 200；code=0；数据库对应字段更新", "app/api/v1/routes/user.py；app/services/user_service.py", "验证可空字段组合更新", "未执行"],
  ["TC-BE-008", "用户与认证", "闯关历史", "闯关历史分页返回用户隔离数据", "高", "接口测试", "用户 1 有多条 quiz 记录；用户 2 有其他记录", "1. 登录用户 1\n2. 调用 GET /api/v1/user/quizzes?page=1&page_size=10", "page=1；page_size=10", "HTTP 200；items 仅包含用户 1 的记录；total、page、page_size 正确", "app/api/v1/routes/user.py；app/services/history_service.py", "验证分页和数据隔离", "未执行"],
  ["TC-BE-009", "用户与认证", "闯关详情", "查询存在的闯关详情成功", "中", "接口测试", "用户 1 存在 quiz_id=quiz_001 的记录", "1. 登录用户 1\n2. 调用 GET /api/v1/user/quizzes/quiz_001", "quiz_id=quiz_001", "HTTP 200；返回题目、答题记录、报告、created_at；不返回其他用户数据", "app/services/history_service.py；app/repositories/quiz_repository.py", "验证详情完整性", "未执行"],
  ["TC-BE-010", "知识库", "文档上传", "上传合法 TXT 文档成功", "高", "接口测试", "用户已登录；文档数量未达上限；文件小于 10MB", "1. 调用 POST /api/v1/knowledge/documents 上传 a.txt", "file=a.txt；内容为有效 UTF-8 文本", "HTTP 200；code=0；返回 doc_id、file_name、status=processing；后台解析后状态变为 ready", "app/api/v1/routes/knowledge.py；app/services/knowledge_service.py", "覆盖上传主流程", "未执行"],
  ["TC-BE-011", "知识库", "文档上传", "上传不支持的文件格式被拒绝", "高", "负向测试", "用户已登录", "1. 调用 POST /api/v1/knowledge/documents 上传 a.xlsx", "file=a.xlsx", "HTTP 400；code=4001；message 包含不支持的文件格式；不写入数据库和本地文件", "app/services/knowledge_service.py", "支持类型仅 pdf/docx/md/txt", "未执行"],
  ["TC-BE-012", "知识库", "文档上传", "文档数量达到上限后拒绝上传", "中", "边界测试", "用户已有 10 篇文档；kb_max_documents_per_user=10", "1. 调用 POST /api/v1/knowledge/documents 上传第 11 篇合法文档", "合法 TXT 文档", "HTTP 400；code=4001；message 包含文档数量已达上限；不创建新文档", "app/services/knowledge_service.py；app/core/config.py", "验证配置上限", "未执行"],
  ["TC-BE-013", "知识库", "文档列表", "文档列表只返回当前用户文档", "高", "接口测试", "用户 1 和用户 2 各有文档", "1. 登录用户 1\n2. 调用 GET /api/v1/knowledge/documents", "Authorization: Bearer <user1 token>", "HTTP 200；items 仅包含用户 1 的 doc_id、file_name、status、chunk_count 等字段", "app/services/knowledge_service.py；app/repositories/knowledge_repository.py", "验证多用户数据隔离", "未执行"],
  ["TC-BE-014", "知识库", "状态查询", "查询不存在的文档状态被拒绝", "中", "负向测试", "用户已登录；doc_missing 不存在或不属于该用户", "1. 调用 GET /api/v1/knowledge/documents/doc_missing", "doc_id=doc_missing", "HTTP 400；code=4001；message=文档不存在", "app/services/knowledge_service.py", "验证归属校验", "未执行"],
  ["TC-BE-015", "知识库", "文档删除", "删除已就绪文档并清理关联资源", "高", "接口测试", "用户已登录；doc_1 状态为 ready；本地文件和向量数据存在", "1. 调用 DELETE /api/v1/knowledge/documents/doc_1\n2. 查询列表和向量库", "doc_id=doc_1", "HTTP 200；code=0；数据库记录、向量、本地文件均被清理；其他文档不受影响", "app/services/knowledge_service.py；app/services/vector_store_service.py", "验证级联清理", "未执行"],
  ["TC-BE-016", "知识库", "数据隔离", "用户向量库按 user_id 隔离", "高", "服务测试", "用户 1 与用户 2 使用同一持久化目录；分别写入不同文档", "1. 调用 similarity_search 查询用户 1 的 doc_1\n2. 再查询用户 2 的 doc_2", "user_id=1/2；doc_id=doc_1/doc_2", "仅返回对应用户和 doc_id 的分块；不发生跨用户读取", "app/services/vector_store_service.py", "Chroma collection 按 kb_user_{user_id} 隔离", "未执行"],
  ["TC-BE-017", "出题", "同步出题", "合法请求生成题库成功", "高", "接口测试", "LLM、搜索或知识库依赖可用；请求不指定 doc_id", "1. 调用 POST /api/v1/quiz/generate", "{\"user_input\":\"学习 Python 基础\",\"question_count\":5,\"difficulty\":\"mixed\"}", "HTTP 200；code=0；返回 quiz_id、title、summary、questions；题目类型、难度、答案结构符合模型", "app/api/v1/routes/quiz.py；app/services/quiz_service.py", "主流程冒烟测试", "未执行"],
  ["TC-BE-018", "出题", "参数校验", "空 user_input 被拒绝", "中", "负向测试", "后端服务已启动", "1. 调用 POST /api/v1/quiz/generate", "{\"user_input\":\"\"}", "HTTP 422；Pydantic 校验失败；不调用 LLM", "app/models/quiz.py", "min_length=1", "未执行"],
  ["TC-BE-019", "出题", "参数校验", "题目数量非法值被拒绝", "中", "边界测试", "后端服务已启动", "1. 分别传入 question_count=2 和 11\n2. 调用 POST /api/v1/quiz/generate", "question_count=2、11", "两次均 HTTP 422；题目数量必须为 3 到 10", "app/models/quiz.py", "同时覆盖下边界外和上边界外", "未执行"],
  ["TC-BE-020", "出题", "参数校验", "非法难度值被拒绝", "中", "负向测试", "后端服务已启动", "1. 调用 POST /api/v1/quiz/generate", "{\"user_input\":\"test\",\"difficulty\":\"impossible\"}", "HTTP 422；difficulty 只允许 easy、medium、hard、mixed", "app/models/quiz.py", "枚举值校验", "未执行"],
  ["TC-BE-021", "出题", "内容安全", "包含敏感词的输入被拒绝", "高", "安全测试", "后端服务已启动", "1. 调用 POST /api/v1/quiz/generate", "{\"user_input\":\"制作炸弹的方法\"}", "HTTP 400；code=4000；message 包含不当内容；不进入 LLM 生成流程", "app/core/security.py；app/main.py", "敏感词过滤", "未执行"],
  ["TC-BE-022", "出题", "知识库出题", "未登录使用 doc_id 出题被拒绝", "高", "安全测试", "请求携带 doc_id；不带 Authorization", "1. 调用 POST /api/v1/quiz/generate", "{\"user_input\":\"总结文档\",\"doc_id\":\"doc_1\"}", "HTTP 400；code=4001；message=使用知识库出题需要先登录", "app/services/quiz_service.py", "验证知识库资源访问控制", "未执行"],
  ["TC-BE-023", "出题", "异步任务", "创建异步出题任务并可轮询结果", "高", "接口测试", "用户已登录；LLM 依赖 Mock 为成功", "1. 调用 POST /api/v1/quiz/generate/async\n2. 轮询 GET /api/v1/quiz/task/{task_id}", "合法出题请求", "创建接口 HTTP 200 且返回 task_id；任务状态从 pending/running 到 completed；completed 时 result 包含 quiz_id 和 questions", "app/api/v1/routes/quiz.py；app/services/quiz_service.py", "覆盖异步状态机", "未执行"],
  ["TC-BE-024", "报告与计分", "学习报告", "合法答题数据生成报告并持久化", "高", "接口测试", "用户已登录；quiz_id 存在；答题记录与题目匹配", "1. 调用 POST /api/v1/report/generate", "quiz_id、topic、questions、answer_records 均有效", "HTTP 200；返回 accuracy、mastered_points、weak_points、three_line_summary、advice、share_quote；答题记录、报告、经验值均保存", "app/api/v1/routes/report.py；app/services/report_service.py", "验证报告生成和落库", "未执行"],
  ["TC-BE-025", "报告与计分", "参数校验", "缺少必需字段的报告请求被拒绝", "中", "负向测试", "后端服务已启动", "1. 调用 POST /api/v1/report/generate，缺少 answer_records", "{\"quiz_id\":\"quiz_1\",\"topic\":\"Python\"}", "HTTP 422；Pydantic 校验失败；不调用 LLM、不写库", "app/models/report.py", "必填字段校验", "未执行"],
  ["TC-BE-026", "报告与计分", "计分服务", "部分正确时正确率和统计值计算正确", "高", "单元测试", "构造 4 条答题记录，其中 3 条 is_correct=true", "1. 调用 compute_score_summary(records)", "4 条记录，3 正确，duration_ms 分别为 1000、2000、3000、4000", "返回 total=4、correct=3、wrong=1、accuracy=75、avg_duration_ms=2500", "app/services/scoring_service.py", "独立验证计算逻辑", "未执行"],
  ["TC-BE-027", "基础组件", "JWT 鉴权", "无效或过期 token 无法通过鉴权", "高", "安全测试", "构造过期 token 和篡改签名 token", "1. 调用 decode_token 解析两种 token\n2. 使用其访问 GET /api/v1/user/profile", "过期 JWT；篡改签名 JWT", "decode_token 抛出 AuthenticationError；接口 HTTP 401、code=4010；不返回用户数据", "app/core/auth.py", "覆盖过期和签名篡改场景", "未执行"],
  ["TC-BE-028", "基础组件", "文档解析", "支持格式加载并按配置分块", "中", "服务测试", "准备 TXT、MD、PDF、DOCX 样例；chunk_size=1000、overlap=150", "1. 分别调用 load_and_split\n2. 检查返回 Document 数量和 metadata", "TXT、MD、PDF、DOCX 样例；chunk_size=1000；chunk_overlap=150", "四种合法格式均返回非空分块；分块大小和重叠符合配置；unsupported 格式抛 ValueError", "app/services/document_loader_service.py", "覆盖格式分发和分块规则", "未执行"],
  ["TC-BE-029", "基础组件", "题目配图", "未登录或额度耗尽时配图安全降级", "中", "异常测试", "user_id=None 或当日生图次数已达 20；出题主流程正常", "1. 请求 generate_images=true 出题\n2. Mock 生图或额度查询", "user_id=None；generate_images=true；当日次数=20", "未登录：返回提示且 image_url 为空；额度耗尽：返回每日限额提示；题目仍正常生成，不抛异常", "app/services/image_service.py；app/services/quiz_service.py", "验证生图失败不影响主流程", "未执行"],
  ["TC-BE-030", "基础组件", "联网搜索", "搜索禁用或失败时返回空上下文", "中", "异常测试", "enable_web_search=false 或 Mock 搜索抛异常/超时", "1. 调用 fetch_knowledge_context\n2. 继续执行出题流程", "enable_web_search=false；或 Mock 搜索超时/异常", "禁用、无 API Key、超时、异常时均返回空字符串；出题流程不被阻断", "app/services/search_service.py；app/services/quiz_service.py", "验证外部依赖降级", "未执行"]
];

cases.getRange("A1:M1").values = [["backend 目录后端测试用例（30条）"]];
cases.getRange("A2").values = [["设计范围"]];
cases.getRange("B2").values = [["backend/app 路由、服务、模型、核心组件，以及 backend/tests 已覆盖行为"]];
cases.getRange("A3:M3").values = [headers];
cases.getRange("A4:M33").values = rows;

// Summary sheet
summary.getRange("A1").values = [["backend 后端测试用例概览"]];
summary.getRange("A2").values = [["生成日期"]];
summary.getRange("B2").values = [[new Date(2026, 8, 11)]];
summary.getRange("A3").values = [["设计范围"]];
summary.getRange("B3").values = [["backend/app 与 backend/tests"]];
summary.getRange("A5:B5").values = [["指标", "数量"]];
summary.getRange("A6:B12").values = [
  ["用例总数", null],
  ["高优先级", null],
  ["中优先级", null],
  ["低优先级", null],
  ["未执行", null],
  ["通过", null],
  ["失败", null],
];
summary.getRange("B6").formulas = [["=COUNTA('测试用例'!$A$4:$A$33)"]];
summary.getRange("B7").formulas = [["=COUNTIF('测试用例'!$E$4:$E$33,\"高\")"]];
summary.getRange("B8").formulas = [["=COUNTIF('测试用例'!$E$4:$E$33,\"中\")"]];
summary.getRange("B9").formulas = [["=COUNTIF('测试用例'!$E$4:$E$33,\"低\")"]];
summary.getRange("B10").formulas = [["=COUNTIF('测试用例'!$M$4:$M$33,\"未执行\")"]];
summary.getRange("B11").formulas = [["=COUNTIF('测试用例'!$M$4:$M$33,\"通过\")"]];
summary.getRange("B12").formulas = [["=COUNTIF('测试用例'!$M$4:$M$33,\"失败\")"]];

summary.getRange("D5:E5").values = [["模块", "用例数"]];
summary.getRange("D6:D11").values = [["系统与健康"], ["用户与认证"], ["知识库"], ["出题"], ["报告与计分"], ["基础组件"]];
summary.getRange("E6:E11").formulas = [
  ["=COUNTIF('测试用例'!$B$4:$B$33,D6)"],
  ["=COUNTIF('测试用例'!$B$4:$B$33,D7)"],
  ["=COUNTIF('测试用例'!$B$4:$B$33,D8)"],
  ["=COUNTIF('测试用例'!$B$4:$B$33,D9)"],
  ["=COUNTIF('测试用例'!$B$4:$B$33,D10)"],
  ["=COUNTIF('测试用例'!$B$4:$B$33,D11)"],
];

// Formatting helpers
const titleStyle = (range) => {
  range.format = {
    fill: "#1F4E78",
    font: { name: fontFamily, bold: true, size: 16, color: "#FFFFFF" },
  };
  range.format.horizontalAlignment = "left";
  range.format.verticalAlignment = "center";
};
const headerStyle = (range) => {
  range.format = {
    fill: "#1F4E78",
    font: { name: fontFamily, bold: true, size: 10, color: "#FFFFFF" },
  };
  range.format.horizontalAlignment = "center";
  range.format.verticalAlignment = "center";
  range.format.wrapText = true;
  range.format.borders = { preset: "all", style: "thin", color: "#FFFFFF" };
};
const bodyStyle = (range) => {
  range.format.font = { name: fontFamily, size: 10, color: "#1F2937" };
  range.format.verticalAlignment = "top";
  range.format.wrapText = true;
  range.format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
};

titleStyle(summary.getRange("A1"));
titleStyle(cases.getRange("A1"));
summary.getRange("A2:B3").format.font = { name: fontFamily, size: 10, color: "#334155" };
summary.getRange("B2").format.numberFormat = "yyyy-mm-dd";
headerStyle(summary.getRange("A5:B5"));
headerStyle(summary.getRange("D5:E5"));
bodyStyle(summary.getRange("A6:B12"));
bodyStyle(summary.getRange("D6:E11"));
summary.getRange("B6:B12").format.numberFormat = "0";
summary.getRange("E6:E11").format.numberFormat = "0";
summary.getRange("A6:A12").format.horizontalAlignment = "left";
summary.getRange("D6:D11").format.horizontalAlignment = "left";
summary.getRange("B6:B12").format.horizontalAlignment = "right";
summary.getRange("E6:E11").format.horizontalAlignment = "right";

cases.getRange("A2:M2").format.font = { name: fontFamily, size: 10, color: "#334155" };
headerStyle(cases.getRange("A3:M3"));
bodyStyle(cases.getRange("A4:M33"));

// Priority and execution result coloring
for (let r = 4; r <= 33; r++) {
  cases.getCell(r - 1, 4).format.horizontalAlignment = "center";
  cases.getCell(r - 1, 12).format.horizontalAlignment = "center";
}
cases.getRange("E4:E33").conditionalFormats.add("containsText", {
  operator: "contains",
  text: "高",
  fill: "#FEE2E2",
  font: { name: fontFamily, bold: true, color: "#991B1B" },
});
cases.getRange("E4:E33").conditionalFormats.add("containsText", {
  operator: "contains",
  text: "中",
  fill: "#FEF3C7",
  font: { name: fontFamily, color: "#92400E" },
});
cases.getRange("M4:M33").conditionalFormats.add("containsText", {
  operator: "contains",
  text: "未执行",
  fill: "#E2E8F0",
  font: { name: fontFamily, color: "#334155" },
});
cases.getRange("M4:M33").conditionalFormats.add("containsText", {
  operator: "contains",
  text: "失败",
  fill: "#FEE2E2",
  font: { name: fontFamily, bold: true, color: "#991B1B" },
});

// Column widths
const caseWidths = [13, 15, 15, 38, 9, 13, 32, 42, 38, 52, 34, 34, 11];
for (let c = 0; c < caseWidths.length; c++) {
  cases.getCell(2, c).format.columnWidth = caseWidths[c];
}
summary.getCell(0, 0).format.columnWidth = 18;
summary.getCell(1, 1).format.columnWidth = 42;
summary.getCell(4, 3).format.columnWidth = 18;
summary.getCell(5, 4).format.columnWidth = 12;

cases.getRange("A1:M1").format.rowHeight = 32;
cases.getRange("A2:M2").format.rowHeight = 22;
cases.getRange("A3:M3").format.rowHeight = 34;
cases.getRange("A4:M33").format.rowHeight = 78;
summary.getRange("A1:E1").format.rowHeight = 32;
summary.getRange("A2:E3").format.rowHeight = 22;
summary.getRange("A5:E12").format.rowHeight = 24;

cases.freezePanes.freezeRows(3);
const table = cases.tables.add("A3:M33", true, "BackendTestCases");
table.showFilterButton = true;

workbook.recalculate();

const inspect = await workbook.inspect({
  kind: "table",
  sheetId: "测试用例",
  range: "A3:M10",
  include: "values,formulas",
  tableMaxRows: 10,
  tableMaxCols: 13,
});
console.log(inspect.ndjson);

const errorScan = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errorScan.ndjson);

const summaryPreview = await workbook.render({ sheetName: "概览", range: "A1:E12", scale: 1, format: "png" });
await fs.writeFile(`${outputDir}/summary.png`, new Uint8Array(await summaryPreview.arrayBuffer()));
const casesPreview = await workbook.render({ sheetName: "测试用例", range: "A1:M12", scale: 1, format: "png" });
await fs.writeFile(`${outputDir}/cases-preview.png`, new Uint8Array(await casesPreview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(`${outputDir}/backend_30_test_cases.xlsx`);
