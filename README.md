# 车库管家 · Garage Keeper（飞牛 fnOS 应用）

车辆保养、维修与能耗记录管理，带账号登录，打包为标准飞牛应用包（`.fpk`），可在应用中心直接安装、启动、停止与卸载。

- 安装包：源码构建产出 `dist/garage-keeper_1.1.0.fpk`（构建方式见第七节；推送 `v*` 标签后由 GitHub Actions 自动打包并附到 Release）
- 运行时：系统自带 `/usr/bin/python3`，**零第三方依赖**，无需 pip、无需联网、无需 Docker
- 数据：SQLite 单文件，位于飞牛应用数据目录，升级与卸载默认保留

---

## 一、安装

1. 打开飞牛 **应用中心** → 右上角 **手动安装**（或「+」→ 安装本地应用）。
2. 选择 `garage-keeper_1.1.0.fpk`，向导分两步：**Web 访问端口**（默认 `8787`）、**管理员账号与密码**（账号默认 `admin`，密码至少 6 位）。
3. 安装完成后，桌面出现「车库管家」图标；也可通过 `http://<NAS-IP>:8787/` 直接访问，首次打开为登录页，用上一步设置的账号登录。

若系统提示来源/签名风险，属于第三方应用的常规提示，确认继续即可。

**备用安装方式（SSH）**：将 fpk 上传到 NAS 后执行

```bash
appcenter-cli install-fpk /vol1/1000/garage-keeper_1.1.0.fpk
```

或使用 `fnos-cli app install-fpk garage-keeper_1.1.0.fpk --volume-id 1 --yes`。

---

## 二、账号与登录

应用为**多账号、单库共享**模型：所有账号看到同一套车辆与记录，账号只用于区分使用者与权限。

| 角色 | 权限 |
| --- | --- |
| 管理员 `admin` | 全部功能；新增 / 停用 / 删除账号、重置密码、恢复备份、清空数据、载入示例 |
| 成员 `member` | 日常记录与查看：车辆、能耗、保养、提醒、智能录入、导出备份、修改自己的密码 |

要点：

- **首次登录强制改密**：若管理员是用默认密码 `garage123` 创建的（例如升级后自动初始化），登录后会要求立即设置新密码，弹窗无法跳过。
- **会话**：登录成功后服务端写入 `HttpOnly` Cookie（`gk_session`），前端不保存任何凭据；勾选「记住登录状态」有效期 14 天，否则 1 天。改密后其他设备的会话自动失效。
- **登录失败限制**：同一 IP / 账号 5 分钟内连续失败 8 次后暂时拒绝，防止暴力猜测。
- **忘记密码**（SSH）：

```bash
cd /var/apps/garage-keeper/target/server
sudo -u garage-keeper python3 garage.py --reset-password --user admin --data /vol1/@appdata/garage-keeper
```

  未指定 `--user` 时默认 `admin`；密码取环境变量 `GARAGE_ADMIN_PASS`，未提供则随机生成并打印在输出中。

- **从 1.0.0 升级**：升级向导会要求填写管理员登录密码，用于为旧数据库补建账号；原有车辆与记录不受影响。

---

## 三、功能

| 模块 | 说明 |
| --- | --- |
| 车辆档案 | 多车辆；区分纯电 / 燃油 / 插混；记录车牌、车架号、初始里程、油箱容积或电池容量、保险公司与保单、保险 / 年检 / 车船税到期日 |
| 能耗记录 | 纯电记录充电量（kWh）、电耗、续航增量、起止电量、费用、充电站；燃油记录加油量（L）、油耗、单价、金额、加油站 |
| 保养维修 | 日期、里程、项目、费用、门店、备注；可登记下次保养日期与里程，自动生成到期提醒 |
| 提醒 | 三类来源合并：法定到期日（保险 / 年检 / 车船税）、保养周期（**日期 + 里程双条件**）、自定义提醒；按逾期 / 即将到期 / 计划中分级 |
| 账号登录 | 安装时设置管理员账号；管理员可新增成员、停用、重置密码；改密、会话过期自动回到登录页 |
| 智能录入 | 自然语言输入一段话，自动拆分为多条结构化记录，逐条可校正后保存；Hermes 不可用时自动降级为本地规则解析 |
| 数据与备份 | JSON 完整备份、CSV 导出（能耗 / 保养 / 车辆）、一次性恢复（合并或覆盖）、CSV 导入 |
| 统计 | 月度支出、油耗 L/100km、电耗 kWh/100km、每公里成本、累计支出（满到满法实测，不做估算填充） |

---

## 四、接入 Hermes（自然语言录入）

在应用内 **设置** 页填写：

| 字段 | 说明 |
| --- | --- |
| 服务地址 | Ollama 本机填 `http://127.0.0.1:11434/v1`；Hermes 在其它设备填 `http://192.168.x.x:11434/v1` |
| 模型名称 | 默认 `hermes3:8b` |
| API Key | 本地 Ollama 留空；vLLM / LM Studio 等按需填写 |
| 超时 / 温度 | 默认 60 秒 / 0.1 |

点击「测试连接」可验证链路。任何网络或解析异常都会自动回退到本地规则引擎，录入流程不会中断。

---

## 五、数据与备份

- 数据目录：`/vol{n}/@appdata/garage-keeper/`（数据库 `garage.db`，含 `users` / `sessions` 账号表），应用内「数据与备份」页会显示实际绝对路径。
- 升级：`app` 程序目录整体替换，数据目录保留。
- 卸载：默认**保留**数据库（含账号）；若在卸载向导中关闭「保留车辆档案与记录」，则同时删除全部数据与账号且不可恢复。

**手动备份整个数据库**（SSH）：

```bash
cp /vol1/@appdata/garage-keeper/garage.db ~/garage-$(date +%F).db
```

建议把该目录纳入飞牛快照或云端同步任务。

---

## 六、端口与启停

- 修改端口：应用中心 → 车库管家 → 设置 → **配置**，保存后服务自动重启。
- 启停：应用中心内提供启动 / 停止按钮（`ctl_stop=true`）。
- 命令行（SSH）：`/var/apps/garage-keeper/cmd/main start|stop|restart|status`，`status` 退出码 `0` 运行中、`3` 已停止。

---

## 七、源码与重新打包

```
fnos/
├── build_fpk.py            # 打包脚本（产出 dist/*.fpk）
├── make_icon.py            # 图标生成（PIL）
└── garage-keeper/          # fpk 源目录
    ├── manifest            # 应用元数据
    ├── ICON.PNG / ICON_256.PNG   # 构建时自动生成，不入库
    ├── garage-keeper.sc    # 防火墙端口声明
    ├── config/             # privilege（运行身份）、resource（资源声明）
    ├── cmd/                # 9 个生命周期脚本
    ├── wizard/             # 安装 / 升级 / 配置 / 卸载向导
    └── app/
        ├── server/         # Python 标准库后端（api / store / calc / nlp / backup）
        └── ui/             # 前端（index.html / app.js / styles.css / config / images）
```

重新打包：

```bash
pip install pillow                 # 仅打包需要（生成图标），应用运行期不依赖
python fnos/build_fpk.py           # 校验结构 → app.tgz → dist/garage-keeper_<version>.fpk
```

- 图标是二进制产物，未纳入版本库；首次构建时若缺失会自动调用 `make_icon.py` 重新生成，也能直接 `python fnos/make_icon.py` 单独执行。
- 打包固定了 tar 与 gzip 的时间戳，**同一份源码重复构建得到的 fpk 校验和完全一致**，便于核对发布包。
- 修改版本号：编辑 `fnos/garage-keeper/manifest` 中的 `version`，脚本会校验 `X.Y.Z` 形式并同步产物文件名。
- 打上 `v1.1.0` 这类标签推送后，可用 `docs/build-fpk.workflow.yml` 作为 GitHub Actions 配置：复制到仓库 `.github/workflows/build-fpk.yml` 即可自动构建 fpk，并上传到 Actions 产物与 Release 附件。

---

## 八、接口一览（供二次开发）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/auth/state` | 登录状态（公开，返回是否需要初始化、当前用户） |
| POST | `/api/auth/login`、`/api/auth/logout` | 登录 / 退出（Cookie 会话） |
| POST | `/api/auth/setup` | 仅当系统无账号时创建管理员 |
| GET | `/api/auth/me` | 当前登录账号 |
| POST | `/api/auth/password` | 修改自己的密码 |
| GET/POST | `/api/auth/users` | 账号列表 / 新建（管理员） |
| PUT/DELETE | `/api/auth/users/{id}` | 改角色或停用 / 删除（管理员） |
| POST | `/api/auth/users/{id}/password` | 重置密码（管理员） |
| GET | `/api/meta` | 版本、车辆简表、数据路径 |
| GET/POST | `/api/vehicles` | 车辆列表 / 新建 |
| GET/PUT/DELETE | `/api/vehicles/{id}` | 详情（含统计与提醒）/ 更新 / 删除 |
| GET/POST | `/api/energy` | 能耗记录（支持 `vehicle_id` `kind` `from` `to` `limit`）/ 新建 |
| PUT/DELETE | `/api/energy/{id}` | 更新 / 删除 |
| GET/POST | `/api/service` | 保养维修记录 / 新建 |
| PUT/DELETE | `/api/service/{id}` | 更新 / 删除 |
| GET/POST | `/api/reminders` | 提醒列表 / 新建 |
| POST/DELETE | `/api/reminders/{id}/done`、`/api/reminders/{id}` | 标记完成 / 删除 |
| GET | `/api/overview` | 总览统计 |
| POST | `/api/ai/parse` | 自然语言解析为结构化记录（不落库） |
| POST | `/api/ai/commit` | 批量落库 |
| POST | `/api/ai/test` | Hermes 连通性测试 |
| GET/PUT | `/api/settings` | 读取 / 更新设置 |
| GET | `/api/export/json`、`/api/export/csv?table=` | 备份 / CSV 导出 |
| POST | `/api/import`、`/api/import/csv` | JSON 恢复 / CSV 导入 |
| POST | `/api/demo-seed`、DELETE `/api/data?confirm=DELETE` | 载入示例数据 / 清空全部 |
