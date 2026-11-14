import asyncio

from market_intelligence.core.config import Settings
from market_intelligence.mcp.langchain_bridge import MCPToolBridge
from market_intelligence.orchestration.graph import build_research_graph


async def main():
    settings = Settings()

    async with MCPToolBridge() as bridge:
        graph = build_research_graph(bridge.tools, settings=settings)

        result = await graph.ainvoke(
            {
                "question": (
                    "Analyze overall retail sales performance "
                    "and identify the top 5 products."
                ),
                "requested_sources": ["internal"],
                "product_limit": 5,
            }
        )

        print("\nANALYST FINDINGS")
        print(result["analyst_findings"])

        print("\nFINAL RESEARCH REPORT")
        print(result["report"])

        print("\nERRORS")
        print(result.get("errors", []))


if __name__ == "__main__":
    asyncio.run(main())