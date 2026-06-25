"""
travel_assistant_demo.py — 🎬 完整演示：DeepAgent 旅行规划器
================================================================
本脚本使用真正的 `deepagents` SDK，在单个 Python 文件中完整实现并演示
Agent Harness 的 9 大核心模组：

  #1  Loop        — 主循环 Think → Act → Observe → Reflect (由 agent.invoke 驱动)
  #2  Context     — 上下文管理 (SummarizationMiddleware + 虚拟文件系统写文件)
  #3  Tools       — 工具管理 (注册 6 个旅行工具与预算工具)
  #4  Skills      — 技能 (通过 skills 路径加载 packing-list 与 travel-tips 技能)
  #5  SubAgents   — 子Agent (注册 hotel-researcher 与 itinerary-planner 子Agent)
  #6  Memory      — 记忆 (启动时自动加载 MEMORY.md 中的用户偏好)
  #7  Prompts     — 提示词 (通过 context_schema 动态注入运行时上下文)
  #8  Hooks       — 生命周期钩子 (LoggingMiddleware 与 BudgetGuardMiddleware)
  #9  Safety      — 安全 (使用 interrupt_on 在 book_flight / book_hotel 前拦截并审批)

"""

import os
import sys
import time
import re
from typing import TypedDict, Any, Sequence, Callable
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 引入 LangChain 核心消息与工具定义
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain.tools import tool
from langchain.agents.middleware import AgentMiddleware, SummarizationMiddleware

# 引入真正的 deepagents 库组件
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from langchain_openai import ChatOpenAI

# ============================================================
# ⚙️ 环境初始化与文件写入
# ============================================================
BASE_DIR = "/Users/sunchang/Documents/projects/deepagent"
SKILLS_DIR = os.path.join(BASE_DIR, "skills")
MEMORY_DIR = os.path.join(BASE_DIR, "memory")

os.makedirs(SKILLS_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)

# 每次运行前删除旧的 travel_plan.md，避免 write_file 工具报 "already exists" 错误
plan_file_path = os.path.join(BASE_DIR, "travel_plan.md")
if os.path.exists(plan_file_path):
    try:
        os.remove(plan_file_path)
    except Exception:
        pass

# 确保 Memory 文件夹中包含 MEMORY.md
MEMORY_FILE = os.path.join(MEMORY_DIR, "MEMORY.md")
with open(MEMORY_FILE, "w", encoding="utf-8") as f:
    f.write("""# 用户旅行偏好 (Memory)
- 预算偏好：中等（酒店住宿预算 ¥300-600/晚）
- 旅游风格：深度文化体验 + 本地美食探索
- 特别需求：需要安静不临街的房间
- 饮食：喜欢川菜吃辣，但肠胃一般，需提醒携带肠胃药
- 上次目的地：2026年5月去了杭州，对西湖国宾馆满意
""")

# 确保 Skills 文件夹中包含技能描述
os.makedirs(os.path.join(SKILLS_DIR, "travel-tips"), exist_ok=True)
with open(os.path.join(SKILLS_DIR, "travel-tips", "SKILL.md"), "w", encoding="utf-8") as f:
    f.write("""---
name: travel-tips
description: 通用的旅行技巧，包含大熊猫基地、太古里等景点的深度游玩和防雨防滑建议。
---
# 旅行技巧
- 7月是成都的雨季，随时随身带伞。
- 大熊猫基地 7:30 开门，一定要上午去，此时熊猫最活跃，下午基本都在睡觉。
- 宽窄巷子适合拍照，吃地道小吃可以去旁边的奎星楼街，性价比高。
""")

os.makedirs(os.path.join(SKILLS_DIR, "packing-list"), exist_ok=True)
with open(os.path.join(SKILLS_DIR, "packing-list", "SKILL.md"), "w", encoding="utf-8") as f:
    f.write("""---
name: packing-list
description: 成都夏季雨季旅行 3 天的必备物品打包清单。
---
# 行李打包清单
- 衣物：短袖 T 恤 x3，短裤/薄长裤 x2，防晒服/薄外套 x1，舒适运动鞋（已穿），拖鞋。
- 药品：肠胃药（吃辣必备）、防蚊喷雾、感冒药、创可贴。
- 数码：大容量充电宝（≥10000mAh）、多头充电线。
""")


# ============================================================
# 📦 Module 7: Prompts (运行时 Context Schema)
# ============================================================
class TravelContext(TypedDict):
    """每次 invoke 时动态传入的运行时上下文"""
    traveler_name: str
    budget_level: str  # "穷游" | "舒适" | "奢华"
    companions: str    # "独自" | "情侣" | "家庭带娃"
    language: str      # 回复语言


# ============================================================
# 🔌 Module 8: Hooks (自定义生命周期钩子 / Middleware)
# ============================================================
class LoggingMiddleware(AgentMiddleware):
    """记录每一次工具调用与 LLM 调用，打印耗时和关键流向"""

    def __init__(self):
        super().__init__()
        self.call_count = 0
        self.total_tool_time = 0.0

    def wrap_tool_call(self, request, handler):
        tool_name = request.tool_call.get("name", "unknown")
        args = request.tool_call.get("args", {})
        self.call_count += 1
        
        is_subagent = (tool_name == "task")
        if is_subagent:
            subagent_type = args.get("subagent_type", "unknown")
            desc = args.get("description", "")
            print("\n" + "🤖" * 40)
            print(f"🚀 [Module #5: SubAgents] 子 Agent 委派启动: {subagent_type}")
            print(f"   任务描述: {desc}")
            print("🤖" * 40)
        else:
            print(f"\n   🔌 [Hook: LoggingMiddleware] >> 工具调用 [{self.call_count}]: {tool_name}")
            print(f"      参数: {args}")
        
        start = time.time()
        result = handler(request)
        elapsed = time.time() - start
        self.total_tool_time += elapsed
        
        if is_subagent:
            print("\n" + "🤖" * 40)
            print(f"✅ [Module #5: SubAgents] 子 Agent {args.get('subagent_type')} 运行完成，耗时 {elapsed:.2f}s!")
            print("🤖" * 40)
        else:
            print(f"   🔌 [Hook: LoggingMiddleware] << 工具执行完毕，耗时 {elapsed:.2f}s")
            print(f"      结果摘要: {str(result)[:150]}...")
        return result

    def wrap_model_call(self, request, handler):
        print(f"\n   🔌 [Hook: LoggingMiddleware] >>  LLM 请求思考...")
        start = time.time()
        result = handler(request)
        elapsed = time.time() - start
        print(f"   🔌 [Hook: LoggingMiddleware] << LLM 思考完毕，耗时 {elapsed:.2f}s")
        return result


class BudgetGuardMiddleware(AgentMiddleware):
    """防线监控：当遇到包含价格的信息时，验证预算健康度"""

    def __init__(self, max_allowed_hotel: float = 800.0):
        super().__init__()
        self.max_allowed_hotel = max_allowed_hotel

    def wrap_model_call(self, request, handler):
        result = handler(request)
        if hasattr(result, "content") and result.content:
            content = str(result.content)
            # 匹配价格标识
            prices = [int(p) for p in re.findall(r"¥([\d,]+)", content.replace(",", ""))]
            for price in prices:
                if price > self.max_allowed_hotel * 3:  # 假设总住宿超出预算
                    print(f"   ⚠️  [Hook: BudgetGuardMiddleware] 警告: 发现单笔大额支出项 ¥{price}，已超出中等预算防线！")
        return result


# ============================================================
# 🔧 Module 3: Tools (工具注册)
# ============================================================
@tool
def search_flights(origin: str, destination: str, date: str) -> str:
    """搜索航班：输入出发地、目的地和日期(YYYY-MM-DD)，返回可用航班列表及票价。"""
    flights = [
        ("CA1401", "08:00", "10:50", 1280, "国航"),
        ("CA4102", "14:30", "17:20", 1450, "国航"),
        ("3U8882", "19:00", "21:50", 980, "川航"),
    ]
    lines = [f"✈️ 航班搜索结果 {origin} → {destination} ({date}):"]
    for fn, dep, arr, price, company in flights:
        lines.append(f"  - {company} {fn} | {dep}→{arr} | ¥{price}")
    return "\n".join(lines)


@tool
def search_hotels(city: str, checkin: str, checkout: str) -> str:
    """搜索酒店：输入城市、入住和退房日期(YYYY-MM-DD)，返回酒店推荐列表及价格。"""
    hotels = [
        ("锦江宾馆", 5, 680, "春熙路商圈，地铁口，闹中取静"),
        ("宽窄巷子客栈", 4, 380, "宽窄巷子景区内，老式四合院"),
        ("全季春熙路店", 3, 280, "春熙路步行街旁，便捷干净"),
        ("太古里博舍", 5, 1500, "太古里中心，奢华现代"),
    ]
    lines = [f"🏨 酒店搜索结果 {city} ({checkin} 到 {checkout}):"]
    for name, star, price, desc in hotels:
        lines.append(f"  - {'★'*star} {name} | ¥{price}/晚 | 描述: {desc}")
    return "\n".join(lines)


@tool
def get_weather(city: str, date: str = "") -> str:
    """查询天气：输入城市名称和日期(可选)，返回天气、气温与湿度。"""
    weather_data = {
        "成都": "🌤️ 多云转晴 | 气温 26°C ~ 32°C | 湿度 65% | 7月属于雨季",
        "北京": "☀️ 晴天 | 气温 24°C ~ 35°C | 湿度 40%",
    }
    w = weather_data.get(city, "🌍 天气数据暂缺")
    prefix = f"📅 {date} " if date else ""
    return f"{prefix}{w}"


@tool
def get_attractions(city: str, days: int = 3) -> str:
    """查询景点：输入城市和旅行天数，返回优先级排序的景点列表。"""
    spots = [
        ("🐼 成都大熊猫繁育研究基地", "最火爆", "建议上午去，看熊猫吃竹子玩耍"),
        ("🏯 武侯祠与锦里古街", "历史文化", "三国圣地，晚上红灯笼亮起很美"),
        ("🌿 杜甫草堂", "诗意人文", "清幽的川西园林与诗圣故居"),
        ("🛍️ 春熙路与太古里", "潮流地标", "时尚商圈，网红打卡地"),
        ("🍜 奎星楼街", "地道美食", "本地人常去的小吃和串串街"),
    ]
    lines = [f"🏙️ {city} 精选景点 (规划天数: {days}天):"]
    for name, tag, tip in spots[:days+1]:
        lines.append(f"  - {name} [{tag}] | 提示: {tip}")
    return "\n".join(lines)


@tool
def calculate_budget(flight_price: float, hotel_price: float, days: int) -> str:
    """计算旅行总预算：输入机票单程价格、酒店单晚价格和旅行天数，计算出总费用明细。"""
    flight_total = flight_price * 2  # 往返
    hotel_total = hotel_price * days
    meals_total = 200.0 * days
    misc_total = 150.0 * days
    total = flight_total + hotel_total + meals_total + misc_total
    
    return f"""📊 旅行总预算明细 (基于 {days} 天):
  - 往返机票总计: ¥{flight_total:,.2f} (单程: ¥{flight_price})
  - 酒店住宿总计: ¥{hotel_total:,.2f} ({days} 晚 x ¥{hotel_price}/晚)
  - 餐饮预算估算: ¥{meals_total:,.2f} (¥200/天)
  - 景区门票交通: ¥{misc_total:,.2f} (¥150/天)
  ------------------------------------
  💰 预估总额: ¥{total:,.2f}"""


@tool
def book_flight(flight_number: str, passenger_name: str) -> str:
    """[安全审批项] 预订机票：完成真实的扣款和出票。需要人工确认。"""
    return f"🎫 [出票成功] 机票预订成功！航班号: {flight_number} | 旅客: {passenger_name} | 票价: ¥1,280"


@tool
def book_hotel(hotel_name: str, guest_name: str, nights: int) -> str:
    """[安全审批项] 预订酒店：完成房间锁定与扣款。需要人工确认。"""
    return f"🏨 [预订成功] 酒店锁定成功！酒店: {hotel_name} | 住客: {guest_name} | 住 {nights} 晚 | 总价: ¥{680 * nights}"


# ============================================================
# 🚀 协调员 Agent 配置系统
# ============================================================
def create_travel_assistant():
    # 使用 DeepSeek API 模型进行加速
    model = ChatOpenAI(
        model="deepseek-v4-pro",
        api_key="<Your API Key>",
        base_url="https://api.deepseek.com",
        temperature=0.0,
    )

    # 8. 初始化钩子 (Hooks)
    logging_mw = LoggingMiddleware()
    budget_mw = BudgetGuardMiddleware(max_allowed_hotel=800.0)

    # 5. 定义子 Agent (SubAgents)
    hotel_researcher = {
        "name": "hotel-researcher",
        "description": "酒店研究专家。筛选并推荐 Top 2 酒店选项。",
        "system_prompt": """你是酒店专家。请立即调用 `search_hotels` 搜索酒店。
在获得结果后，直接推荐2家安静、中等预算的酒店（如宽窄巷子客栈与全季春熙路店）。
重要：严禁冗长解释或废话，直接调用工具，回复控制在 30 字以内！思考必须少于 1 行！用中文回复。""",
        "tools": [search_hotels],
        "model": model,
    }

    itinerary_planner = {
        "name": "itinerary-planner",
        "description": "行程规划专家。负责制定 3 日详细行程，并计算预算。",
        "system_prompt": """你是行程规划专家。请：
1. 立即并行调用 `get_attractions` 并调用 `calculate_budget`（机票单程使用 1280，酒店使用 380，天数 3 天）。
2. 获取结果后，直接输出一句话行程概要和总预算，控制在 50 字以内！
重要：严禁冗长解释或废话，直接并行调用工具！思考必须少于 1 行！用中文回复。""",
        "tools": [get_attractions, calculate_budget],
        "model": model,
    }

    checkpointer = MemorySaver()
    backend = FilesystemBackend(virtual_mode=False)

    # 1. 2. 3. 4. 5. 6. 7. 8. 9. 模块的深度融合
    agent = create_deep_agent(
        model=model,
        # 2. 上下文管理后端
        backend=backend,
        # 3. 注册主工具
        tools=[search_flights, get_weather, book_flight, book_hotel],
        # 4. 加载 Skills 目录
        skills=[SKILLS_DIR],
        # 6. 加载 Memory 文件
        memory=[MEMORY_FILE],
        # 5. 加载 SubAgents 数组
        subagents=[hotel_researcher, itinerary_planner],
        # 7. 注入 Prompts 的 context schema
        context_schema=TravelContext,
        # 8. 挂载中间件钩子
        middleware=[logging_mw, budget_mw],
        # 9. 开启 Safety 人工审批
        interrupt_on={"book_flight": True, "book_hotel": True},
        checkpointer=checkpointer,
        system_prompt="""你是旅行助手。请遵循极简原则，每次回复字数极少，必须用中文回复：
- 如果用户要求预订机票或预订酒店（如包含“预订”、“订机票”、“book”等词），请立即从上下文中提取姓名、航班号和酒店名，并并行调用 `book_flight` 和 `book_hotel` 工具！
- 否则，如果用户要求规划旅行，请按以下步骤快速且并行完成：
  1. 第一步：必须并行调用 `search_flights`（北京到成都，7月1日）、`get_weather`（成都，7月1日），并同时使用 `read_file` 读取：
     - `/Users/sunchang/Documents/projects/deepagent/skills/travel-tips/SKILL.md`
     - `/Users/sunchang/Documents/projects/deepagent/skills/packing-list/SKILL.md`
     - `/Users/sunchang/Documents/projects/deepagent/memory/MEMORY.md`
  2. 第二步：直接调用子 Agent `hotel-researcher` 和 `itinerary-planner`（把之前收集到的天气、航班、喜好等作为输入传给子Agent）。
  3. 第三步：调用 `write_file` 把精简行程方案（约100字）写入 `/Users/sunchang/Documents/projects/deepagent/travel_plan.md`。
  4. 第四步：输出超简短总结并结束。

重要：严禁生成任何多余文字或废话，每次思考必须少于 1 行，直接输出工具调用！""",
    )

    return agent


# ============================================================
# 🎬 演示主程序
# ============================================================
if __name__ == "__main__":
    print("=" * 80)
    print("  🧳 DeepAgent 智能旅行规划器 — 9 大核心模组全集成演示")
    print("=" * 80)

    # 1. 检查 DeepSeek API 连通性
    print("📡 正在检查 DeepSeek API 服务连通性...")
    import urllib.request
    import urllib.error
    try:
        urllib.request.urlopen("https://api.deepseek.com", timeout=5)
        print("   ✅ DeepSeek 服务网络连通正常。")
    except urllib.error.HTTPError as e:
        print("   ✅ DeepSeek 服务网络连通正常。")
    except Exception as e:
        print(f"   ❌ 无法连接到 DeepSeek API ({e})。请检查网络！")
        sys.exit(1)

    print("🧩 初始化 9 大 Harness 模组并创建 DeepAgent...")
    agent = create_travel_assistant()
    config = {"configurable": {"thread_id": "traveler_session_001"}}

    # ============================================================
    # Phase 1: 主循环规划行程 (Loop, Context, Tools, Skills, SubAgents, Memory, Prompts, Hooks)
    # ============================================================
    print("\n" + "=" * 80)
    print("🔄 PHASE 1: 规划与决策 (Think → Act → Observe → Reflect)")
    print("=" * 80)
    print("用户输入: '我计划7月1日从北京去成都玩3天。请帮我完整研究并制作旅行方案，最后写入文件。'")
    
    # 7. 运行时传入动态上下文 (TravelContext)
    travel_context = {
        "traveler_name": "X先生",
        "budget_level": "舒适",
        "companions": "情侣",
        "language": "中文"
    }

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "我计划7月1日从北京去成都玩3天。请帮我完整研究并制作旅行方案，最后写入文件。"
                }
            ],
            "context": travel_context
        },
        config=config
    )

    # 查找并打印 AI 的最终规划输出
    final_plan_text = ""
    for msg in reversed(result.get("messages", [])):
        if msg.type == "ai" and msg.content:
            final_plan_text = msg.content
            break

    print("\n" + "=" * 80)
    print("🤖 Agent 生成的规划方案:")
    print("=" * 80)
    print(final_plan_text)

    # 2. 上下文虚拟文件系统检查
    print("\n" + "=" * 80)
    print("📂 PHASE 2: 虚拟文件系统 (Context) 写入验证")
    print("=" * 80)
    plan_file_path = os.path.join(BASE_DIR, "travel_plan.md")
    if os.path.exists(plan_file_path):
        print(f"✅ 成功在本地检测到生成的旅行方案文件: {plan_file_path}")
        print("--- 文件前 10 行内容展示 ---")
        with open(plan_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[:10]:
                print(f"  | {line.rstrip()}")
    else:
        print("⚠️ 虚拟文件尚未在物理磁盘落地（可能是由于模型只在虚拟内存中创建，未调用 write_file 写入物理盘），我们将直接把内容写入该文件。")
        with open(plan_file_path, "w", encoding="utf-8") as f:
            f.write(final_plan_text)
        print(f"✅ 已直接落地写入文件: {plan_file_path}")

    # ============================================================
    # Phase 3: 人工安全审批演示 (Safety)
    # ============================================================
    print("\n" + "=" * 80)
    print("🔒 PHASE 3: Safety 安全模组 & 人工审批拦截 (Human-in-the-Loop)")
    print("=" * 80)
    print("用户发送: '我是X先生，方案非常满意！帮我订机票 CA1401，并帮预订锦江宾馆。'")

    booking_result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "我是X先生，方案非常满意！帮我订机票 CA1401，并帮预订锦江宾馆。"
                }
            ],
            "context": travel_context
        },
        config=config
    )

    # 检查状态是否暂停，需要审批
    state = agent.get_state(config)
    print("\n--- 调试：当前 State 中的完整消息历史 ---")
    for i, m in enumerate(state.values.get("messages", [])):
        print(f"  [{i}] {m.type}: {str(m.content)[:150]}...")
    
    print(f"\n📡 检查当前 Graph 运行状态:")
    print(f"   - 下一步节点: {state.next}")
    
    if state.next:
        print(f"\n🚨 [Safety Interrupt] 成功触发安全策略拦截！")
        print("   主协调员已暂停执行敏感预订操作，等待人工授权。")
        print("   需要授权的敏感动作 (Action Requests):")
        for task in state.tasks:
            for interrupt_info in getattr(task, "interrupts", []):
                hitl_request = interrupt_info.value
                if isinstance(hitl_request, dict):
                    for action in hitl_request.get("action_requests", []):
                        print(f"     👉 动作: {action.get('name')} | 参数: {action.get('args')}")

        print("\n⏳ 正在模拟安全管理控制台动作：[审批通过 ALL]")
        # 构造审批批准指令
        # 对应 state.tasks 中的两个敏感操作 book_flight 和 book_hotel，按顺序传入 approve
        resume_command = Command(
            resume={"decisions": [{"type": "approve"}, {"type": "approve"}]}
        )
        
        print("🔄 正在向 Agent 发送恢复指令，继续执行...")
        resumed_result = agent.invoke(resume_command, config=config)
        
        # 提取恢复后的最终回复
        final_reply = ""
        for msg in reversed(resumed_result.get("messages", [])):
            if msg.type == "ai" and msg.content:
                final_reply = msg.content
                break
        
        print("\n" + "=" * 80)
        print("🤖 审批通过后 Agent 的后续执行与回复:")
        print("=" * 80)
        print(final_reply)
    else:
        # 提取最终回复
        final_reply = ""
        for msg in reversed(booking_result.get("messages", [])):
            if msg.type == "ai" and msg.content:
                final_reply = msg.content
                break
        print(f"\n⚠️ 未触发安全策略拦截。AI 回复: {final_reply}")

    print("\n" + "=" * 80)
    print("🎉 9 大 Agent Harness 模组运行完毕，演示圆满结束！")
    print("=" * 80)
