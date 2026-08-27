"""checkers 包：按产物类型实现结构与确定性缺陷的判定内核。

与 `extractors`（读内容）对称 —— 这里只做**判定**，不做输出格式与退出码：结果按
`deliverable-verify` 的 `checks[].status` 四档（fail / warn / skip / pass）回给
`defect_check.py`，全技能只有一套判定标准。

不做按扩展名的路由：`defect_check.py` 本身就是按类型分支的，多一层分发只是多一层间接。
"""
