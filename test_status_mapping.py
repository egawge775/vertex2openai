"""上游错误状态码映射回归测试（与本项目 app/ 同级，不参与 Docker 镜像构建）。

背景：本代理曾把上游 `429 RESOURCE_EXHAUSTED` 在重试耗尽后统一吐成 HTTP 500，
导致 new-api / one-api 等下游网关把「暂时限流」误判为「渠道故障」。
本测试锁定修复后的映射规则，防止回归。

运行（需要项目依赖已安装）：
    python test_status_mapping.py
    # 或在项目目录内：  python app/../test_status_mapping.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

import api_helpers as ah  # noqa: E402

# 截图里的真实上游错误串：外层被包成 status_code=500，内层其实是 429 RESOURCE_EXHAUSTED
REAL_MSG = (
    "status_code=500, 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, "
    "'message': 'Resource exhausted. Please try again later.', "
    "'status': 'RESOURCE_EXHAUSTED'}}"
)


class FakeAPIError(Exception):
    """模拟 google.genai.errors.APIError：带 .code 属性与完整 message。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# (说明, 异常, 期望状态码)
CASES = [
    ("截图真实错误（code=500 + RESOURCE_EXHAUSTED 文案）", FakeAPIError(500, REAL_MSG), 429),
    ("SDK 正确抛 429", FakeAPIError(429, REAL_MSG), 429),
    ("503 UNAVAILABLE（上游过载）",
     FakeAPIError(503, "503 UNAVAILABLE. {'error': {'code': 503}}"), 429),
    ("纯 RESOURCE_EXHAUSTED 文案、无 code", Exception("RESOURCE_EXHAUSTED"), 429),
    ("超出配额（quota）", Exception("You exceeded your current quota"), 429),
    ("404 模型不存在",
     FakeAPIError(404, "404 NOT_FOUND. Publisher model was not found"), 404),
    ("403 需要计费",
     FakeAPIError(403, "403 PERMISSION_DENIED. requires billing to be enabled"), 403),
    ("400 参数非法",
     FakeAPIError(400, "400 INVALID_ARGUMENT. Requests ending with a model turn"), 400),
    ("真·未知错误（保持 500）", Exception("some unexpected internal bug"), 500),
    ("连不上上游（节点挂 / 代理不通）", Exception("All connection attempts failed"), 503),
    ("连接超时", Exception("ConnectTimeout: timed out"), 503),
    ("上游超时", Exception("504 Deadline Exceeded"), 504),
]


def main() -> int:
    ok = True

    print("A) extract_upstream_error —— 非流式路由兜底路径")
    for name, exc, want in CASES:
        got, _ = ah.extract_upstream_error(exc)
        good = got == want
        ok &= good
        print(f"  [{'OK' if good else 'FAIL'}] {name} -> 期望 {want} / 实际 {got}")

    print()
    print("B) classify_upstream_error —— 流式错误帧（含 error type）")
    for name, exc, want in CASES:
        got, etype = ah.classify_upstream_error(getattr(exc, "code", None) or 500, exc)
        good = got == want
        ok &= good
        print(f"  [{'OK' if good else 'FAIL'}] {name} -> 期望 {want} / 实际 {got} ({etype})")

    print()
    print("C) 关键回归：限流不能被还原成 500；无异常信息时仍保持 500")
    e = FakeAPIError(500, REAL_MSG)
    checks = [
        ("extract_upstream_error", ah.extract_upstream_error(e)[0], 429),
        ("classify(500, 限流异常)", ah.classify_upstream_error(500, e)[0], 429),
        ("classify(500, 无异常信息)", ah.classify_upstream_error(500, None)[0], 500),
    ]
    for label, got, want in checks:
        good = got == want
        ok &= good
        print(f"  [{'OK' if good else 'FAIL'}] {label} -> 期望 {want} / 实际 {got}")

    print()
    print("结果:", "全部通过" if ok else "存在失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
