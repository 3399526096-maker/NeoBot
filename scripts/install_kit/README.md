# NeoBot 懒人安装包

在目标机器上跑一条命令把 NeoBot 装起来，并且**检查 NapCat 与 QQ 的版本是否配套**。

## 怎么用

1. 解压本目录
2. 确认本机装了 **Python 3.13+**（安装时记得勾选 "Add to PATH"）
3. 运行：

```bash
python install.py
```

想先看看它要做什么，加 `--dry-run`：

```bash
python install.py --dry-run
```

装完用生成的启动脚本启动：

- Windows：`start-neobot.bat`
- Linux/macOS：`./start-neobot.sh`

首次启动后打开网页面板（默认 <http://127.0.0.1:9981>）。
**出厂模型库是空的** —— 面板会自动弹出「接入模型 · 三步走」教程，
按它填供应商与模型即可。填好后点「软重启运行」就开始工作。

## ⚠️ NapCat 与 QQ 的版本必须配套

NapCat.Shell **不是独立程序**，它注入进官方的 QQNT 客户端来提供 OneBot 接口。
所以它是针对**特定 QQ 版本**构建的，两边对不上时：

> **不会报错**，只表现为登录后频繁被踢下线、反复掉线重连。

这种症状很容易被当成网络问题排查半天。本工具会在安装时主动检查并告警：

```
  找到: C:\Program Files\Tencent\QQNT\QQ.exe
  版本: 9.9.35-52892
  !! 版本不配套：NapCat v4.18.28 面向 QQ 9.9.26-44343，而本机是 9.9.35-52892
```

对不上时，二选一：

- 装一个配套版本的 QQNT（推荐，改动最小）
- 换一个适配本机 QQ 的 NapCat.Shell

已知的配套关系记在 `qq_version.py` 的 `KNOWN_GOOD_PAIRS` 里，
随上游更新时在那里补一行即可。

## 目录内容

| 路径 | 说明 |
|---|---|
| `install.py` | 安装器（本目录唯一需要你运行的脚本） |
| `qq_version.py` | QQ/NapCat 版本检测；也可单独跑做自检：`python qq_version.py` |
| `wheels/` | 离线依赖包。有它就纯离线安装，不需要目标机器联网 |
| `napcat/` | NapCat.Shell，安装时会被复制到 `<安装目录>/napcat` |

## 没有 wheels/ 或 napcat/ 怎么办

说明这个包是精简构建的，安装时需要联网（或你自行补齐）。可以在有网的机器上重新构建：

```bash
python build_kit.py                       # 收集依赖 + 下载 NapCat，产出完整 zip
python build_kit.py --napcat-zip X.zip    # 用本地已下好的 NapCat 包
python build_kit.py --mirror https://ghproxy.net/   # GitHub 访问不稳时走代理
```

## 装完之后

1. **接模型**：面板 → 教程 → 三步走（环境变量 → 模型库 → 模型分配）
2. **NapCat 登录 QQ**：首次需要扫码，登录态会保存在 NapCat 目录里
3. **设置面板密码**：面板首次打开会提示设置，或在 QQ 私聊机器人发 `/set_password`

## 这个安装包不做什么

- **不安装、不升级、不卸载你的 QQ** —— 那是你自己机器上的东西，工具只读取它的版本号来判断兼容性
- **不代替你登录 QQ** —— 扫码那一步必须本人操作
- **不修改系统代理、防火墙等设置**
