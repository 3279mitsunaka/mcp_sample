import asyncio
import sys
from typing import List, Dict, Any
from contextlib import AsyncExitStack
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession
from langgraph.prebuilt import create_react_agent
from langchain_ollama import ChatOllama


# Clientクラス
class MCPClient:
    def __init__(self, server_name: str, server_path: str):
        self.server_name = server_name
        self.server_path = server_path
        self.session = None
        self.exit_stack = None
        self.tools = []

    async def connect_to_server(self):
        if self.exit_stack:
            await self.exit_stack.aclose()
        self.exit_stack = AsyncExitStack()

        # server設定
        server_params = StdioServerParameters(command="python", args=[self.server_path])
        # 今回は非同期複数起動を視野に入れているので with は使いません
        # サーバ接続のためのクライアントストリームを確立
        try:
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            self.read, self.write = stdio_transport
            self.session = await self.exit_stack.enter_async_context(
                ClientSession(self.read, self.write)
            )
            # 初期化処理（initialize）
            await self.session.initialize()

            # ツール呼び出し
            response = await self.session.list_tools()
            self.tools = [
                {
                    "name": _tool.name,
                    "description": _tool.description,
                    "input_schema": _tool.inputSchema,
                }
                for _tool in response.tools
            ]
            self.tool_server_map = {
                _tool.name: self.server_name for _tool in response.tools
            }
            print(
                "\n**サーバー接続**\n利用可能ツール：",
                [_tool.name for _tool in response.tools],
            )
            return True
        except Exception as e:
            print(f"Client -> x -> Server: {self.server_name}")
            print(e)
            self.session = None
            return False


# 各Clientを束ねるクラス
class Host:
    def __init__(self):
        self.clients_list: Dict[str, MCPClient] = {}  # Server_name -> MCPClinet
        self.all_tools_map: Dict[str, str] = {}  # tool_name -> Server_name
        self.running = True
        self.conv_history: List[Dict[str, str]] = []  # [role, content]

    async def add_server(self, server_name: str, server_path: str):
        if server_name not in self.clients_list:
            client = MCPClient(server_name, server_path)
            self.clients_list[server_name] = client
            print(f"[systm] Server: {server_name} を追加")

    async def connect_all_server(self):
        print("[systm] Server connecting...")
        tmp = []
        for server_name, client in self.clients_list.items():
            if await client.connect_to_server():
                for _tool_name, _src_server_name in client.tool_server_map.items():
                    if _tool_name not in self.all_tools_map:
                        self.all_tools_map[_tool_name] = _src_server_name
                tmp.append(server_name)
        print(f"\n[systm] Server connected! -> {tmp}")

    def _get_llm_tool_definitions(self) -> List[Dict[str, Any]]:
        # LLMの関数呼び出しに適したツール定義のリストを生成する。
        llm_tools = []
        for _server_name, _client in self.clients_list.items():
            if _client.session and _client.tools:  # 接続済みのクライアントのツールのみ
                for tool in _client.tools:
                    # OpenAIの関数呼び出し形式を例にとる
                    # 'input_schema' はツールの引数を定義するJSONスキーマ
                    llm_tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tool["name"],
                                "description": tool["description"],
                                "parameters": tool[
                                    "input_schema"
                                ],  # このスキーマがJSON形式である必要
                            },
                        }
                    )
        return llm_tools

    async def start_conversation(self, llm):
        # 指定された Client の接続を試みる
        await self.connect_all_server()

        # 応答ループ
        print("\nセッションを開始。専用コマンドリストは'--help'で確認")
        while self.running:
            try:
                user_input = await asyncio.to_thread(input, "You: ")
                if user_input.lower() == "--help":
                    print("--list : 利用可能サーバーの表示\n" "--exit : セッション終了")
                elif user_input.lower() == "--list":
                    print("利用可能ツール")
                    for _tool_name, _server_name in self.all_tools_map.items():
                        client = self.clients_list.get(_server_name)
                        if client and client.session:
                            print(f"  - {_server_name} -> {_tool_name}")
                elif user_input.lower() == "--exit":
                    print("セッション終了")
                    self.running = False
                    break
                else:
                    # ここにLLM処理
                    # 会話履歴にユーザー入力を追加
                    # 注：会話履歴は一応保存しているもののうまく活用できていないです。スミマセン
                    self.conv_history.append({"role": "user", "content": user_input})

                    # ツール取得
                    llm_tools = self._get_llm_tool_definitions()
                    # エージェント接続
                    agent = create_react_agent(llm, llm_tools)
                    # クエリ送信
                    result = await agent.ainvoke({"messages": user_input})
                    # print(result)
                    tool_calls_list = result["messages"][1].tool_calls[0]
                    tool_calls = dict(tool_calls_list)
                    # print(tool_calls)

                    if tool_calls["type"] == "text":
                        # LLMがテキスト応答を提案
                        agent_response = result["content"]
                        # おしゃべり
                        print(f"agent: {agent_response}")
                        # 履歴保存
                        self.conv_history.append(
                            {"role": "assistant", "content": agent_response}
                        )

                    elif tool_calls["type"] == "tool_call":
                        # LLMがツール呼び出しを提案
                        tool_name_to_call = tool_calls["name"]
                        tool_args = tool_calls.get("args", {})
                        try:
                            target_server_name = self.all_tools_map.get(
                                tool_name_to_call
                            )
                            target_client = self.clients_list.get(target_server_name)
                            if target_client and target_client.session:
                                tool_result = await target_client.session.call_tool(
                                    tool_name_to_call, tool_args
                                )
                            else:
                                tool_result = f"Server:{target_server_name} 未接続"
                        except Exception as e:
                            exception_type, exception_object, exception_traceback = (
                                sys.exc_info()
                            )
                            print(f"error:{exception_traceback.tb_lineno}:{str(e)}")
                            tool_result = f"{tool_name_to_call}が見つかりません"
                        # 本来なら再度この結果をLLMに伝えるのがよい。
                        # 今回は省略
                        print(f"ツール結果: {tool_result}")

            except EOFError:
                print("Finished.")
                self.running = False

            except Exception as e:
                print("Failed to connect.")
                exception_type, exception_object, exception_traceback = sys.exc_info()
                print(f"error:{exception_traceback.tb_lineno}:{str(e)}")
                self.running = False

        # 全てのクライアントのexit_stackをクローズ
        for _client in self.clients_list.values():
            if _client.exit_stack:
                await _client.exit_stack.aclose()
                await asyncio.sleep(1)
                print(f"Client: {_client.server_name} のセッションを閉じました。")
        print("--- 全てのセッションクローズ完了 ---")


async def main():
    host = Host()

    # ここに追加したサーバーを追加します
    await host.add_server("Tools", "tools_server.py")
    await host.add_server("SolidWorks_Tools", "solidworks_server.py")

    # LLM設定はここ
    llm = ChatOllama(
        model="llama3.2",
        temperature=0,
        base_url="http://localhost:11434",
    )
    await host.start_conversation(llm)


if __name__ == "__main__":
    asyncio.run(main())
