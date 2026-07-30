上游版本
========

第三方上游项目（不在本仓库内复制完整源码，只记录获取方式）

cc-connect
  仓库 https://github.com/chenhg5/cc-connect.git
  分支 main
  HEAD fc315d213b49d62e9d90ea4a510189d4115e636f
  获取: git clone 后 checkout fc315d2，应用 integrations/cc-connect/patches/ 下 5 个 Patch
  许可证: 见上游仓库 LICENSE
  我们只保存自己的 5 个 Patch 和构建脚本，不复制完整上游源码

Hermes
  安装位置 <LOCALAPPDATA>/hermes/hermes-agent/
  版本 v0.19.0
  editable install
  我们的适配层在 src/hermes-adapter/，作为 Hermes 插件加载，不修改 Hermes 本体

Claude Code
  CLI v2.1.220
  官方工具，本仓库不复制

Codex
  CLI 0.145.0
  官方工具，本仓库不复制

Node / Python / Go
  node v24.16.0 / npm 11.13.0 / python 3.11.15 / go go1.26.5
  运行环境，本仓库不包含
