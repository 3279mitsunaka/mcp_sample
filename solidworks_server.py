from mcp.server.fastmcp import FastMCP
import win32com.client
from win32com.client import VARIANT
import pythoncom
import asyncio


mcp = FastMCP("SolidWorks_Tools")


@mcp.tool()
async def draw_cylinder() -> bool:
    """Start SolidWorks and draw a cylinder."""

    # SolidWorks を起動
    try:
        swApp = win32com.client.GetActiveObject("SldWorks.Application")
    except Exception:
        swApp = win32com.client.Dispatch("SldWorks.Application")
    swApp.Visible = True  # GUI を見える状態にする
    await asyncio.sleep(1)

    # 新しい部品ドキュメントを作成
    # 第一引数でテンプレートデータを指定できる　※指定しないとエラーになる
    template_path = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2025\templates\部品.prtdot"
    modelDoc = swApp.NewDocument(template_path, 0, 0, 0)
    if modelDoc is None:
        raise RuntimeError("ドキュメント作成に失敗しました。テンプレートパスを確認してください。")

    # おまじない
    await asyncio.sleep(5)

    # FeatureManager 取得
    featureMgr = modelDoc.FeatureManager

    # スケッチ作成準備
    empty_dispatch = VARIANT(pythoncom.VT_DISPATCH, None)
    success = modelDoc.Extension.SelectByID2(
        "平面",    # str: name
        "PLANE",        # str: type
        0, 0, 0,    # double: X, Y, Z
        False,      # bool: Append
        0,      # int: Mark
        empty_dispatch,   # callout
        0       # int SelectOption
        )
    if not success:
        # 英語版と日本語版とで表記が異なるらしいです by.ChatGPT-4o
        success = modelDoc.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, empty_dispatch, 0)
        if not success:
            raise RuntimeError("平面（Front Plane）の選択に失敗しました")

    # スケッチ開始
    modelDoc.SketchManager.InsertSketch(True)

    # スケッチに円を描く（原点中心、直径0.05m）
    modelDoc.SketchManager.CreateCircleByRadius(0, 0, 0, 0.025)

    # おまじない
    await asyncio.sleep(1)

    # スケッチを押し出す
    featureMgr.FeatureExtrusion3(
        True,  # bool: Sd,押し出し
        False,  # bool: Flip,双方向でない
        False,  # bool: Dir, 薄版でない
        0, 0,  # int: T1,T2
        0.02, 0.0,    # double D1,D2
        False, False,   # bool: Dchk1,2
        False, False,   # bool: Ddir1,2
        0.0, 0.0,   # double: Dang1,2
        False, False,   # bool: OffsetReverse1,2
        False, False,   # bool: TranslateSurface1,2
        True,   # bool: Merge
        True,   # bool: UseFeatScope
        True,   # bool: UseAutoSelect
        0,      # int: T0
        0.0,    # double: StartOffset
        False   # bool: FlipStartOffset
    )

    # スケッチ終了
    modelDoc.SketchManager.InsertSketch(True)

    return True


if __name__ == "__main__":
    mcp.run(transport="stdio")
