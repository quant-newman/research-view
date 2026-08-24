"""B1 批量真调实测:8 条真实风格新闻一次送,验对齐/不串扰/数值不换算。不落库。"""
import sys, json
sys.path.insert(0, "/home/ubuntu/mofangrearch/src")
from research_view import structure as S

ROWS = [
 (1, "兆易创新:DRAM 现货价环比上涨 18%,公司 NOR Flash 库存降至 6 周",
     "机构调研纪要显示,10 月以来 DRAM 现货价环比上涨 18%,公司 NOR Flash 渠道库存由年初的 12 周降至 6 周。"),
 (2, "工信部发布《算力基础设施高质量发展行动计划》,2027 年算力规模目标 300 EFLOPS",
     "计划提出到 2027 年全国算力规模超过 300 EFLOPS,智能算力占比达到 35%。"),
 (3, "某新股上市首日涨 62204%(未做拆分调整)",
     "该股上市首日较发行价上涨 62204%,交易所提示风险。"),
 (4, "泳池清洁机器人厂商元鼎智能递交招股书", "公司主营泳池清洁机器人,2025 年营收 9.8 亿元。"),
 (5, "澜起科技澄清:网传其获某北美客户 CXL 大单不实", "公司发布澄清公告,称网络传闻不属实,未签署相关订单。"),
 (6, "贵州茅台前三季度营收增长 11%", "公司披露三季报,营收同比增长 11%。"),
 (7, "中际旭创:800G 光模块Q4排产环比提升,已通过某海外云厂验证",
     "公司在业绩说明会表示 800G 光模块四季度排产环比提升,并已通过一家海外云厂商验证。"),
 (8, "英伟达发布 Rubin 架构,单卡显存带宽较 Blackwell 提升 1.6 倍",
     "英伟达在 GTC 发布 Rubin 架构,官方称单卡显存带宽较 Blackwell 提升 1.6 倍。"),
]

j = S.llm.chat_json(S.SYSTEM, S._prompt([(t, c) for _, t, c in ROWS]))
got = S._align(j, len(ROWS))
print(f"== 送入 {len(ROWS)} 条,对齐回 {len(got)} 条,调用 1 次(旧口径需 8 次)==\n")
for i, (nid, title, _) in enumerate(ROWS):
    it = got.get(i)
    if not it:
        print(f"[{i}] ✗未对齐 | {title[:30]}"); continue
    print(f"[{i}] {title[:34]}")
    print(f"     情绪={it.get('sentiment')} 类型={it.get('event_type')} 科技={it.get('is_chain_relevant')} 票={it.get('tickers')}")
    print(f"     一句话={it.get('one_line')}")
    print(f"     摘要={it.get('summary')}\n")
