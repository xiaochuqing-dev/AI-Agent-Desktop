reference-baseline 事实源
==========================

一、事实源优先级
----------------
第一: 实际文件、Git Commit、Patch 文件、SHA256 实测值
第二: 当前运行配置和真实 E2E 证据
第三: 本目录和根目录文档
第四: history-minimal/ 历史摘要（仅参考）

二、当前事实
------------
Tag: v0.1-reference-baseline
baseline HEAD: cd3493b191fdc19114e0ae037746ab3d23a58a79
cc-connect 运行版本: v1.4.1-patchset0.1-fc315d2
cc-connect SHA256: f7a577bba84bf732519d98cfdf70fa6c089fbc50ae9e14deb775d3c46d0409fb
cc-connect 上游: fc315d213b49d62e9d90ea4a510189d4115e636f
Hermes 修复: 383375d（dual_agent 配置化）+ cd3493b（planner 顺序识别）

三、源码对齐
------------
src/ 中的源码与当前运行体一致（见根目录 CURRENT_RUNTIME_SOURCE_MAP.md）。
修改 src/ 即在修改当前真实集成代码。

四、不一致处理
--------------
发现文档与实际 Git/SHA256 不一致，以实际为准，停下报告，不猜测，不擅自修改消除不一致。
