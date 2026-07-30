04 参考基线
============

一、Tag
-------
v0.1-reference-baseline
含义: 当前参考实现可从正式源码、配置、Patch 和构建脚本恢复，并通过 Telegram 群聊与 Hermes 私聊真实 E2E。
不是最终产品 v0.1.0。

二、版本
--------
baseline HEAD: cd3493b191fdc19114e0ae037746ab3d23a58a79
cc-connect 运行: v1.4.1-patchset0.1-fc315d2，SHA256 f7a577bb...
cc-connect 上游: fc315d213b49d62e9d90ea4a510189d4115e636f
Patch-set: 0.1，5 个 Patch

三、E2E 结果
------------
群聊 9 项通过、Hermes 私聊 3 项通过。详见 reference-baseline/E2E_VALIDATION.md。

四、已知限制
------------
见 reference-baseline/KNOWN_ISSUES.md。

五、当前仍是参考实现
--------------------
v0.1-reference-baseline 不代表最终产品架构。
冻结后不在 Hermes 插件和 cc-connect Patch 上继续堆功能。
Control Plane v1 设计包已经形成，但不改变本参考基线。
下一阶段审阅并冻结 Control Plane v1 契约，然后实现第一个最小纵向切片。
