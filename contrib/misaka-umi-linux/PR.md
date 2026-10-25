# PR：给 misaka-link/umi-linux 补上面板驱动

**已提交：<https://github.com/misaka-link/umi-linux/pull/1>**
（fork `colorgarden/umi-linux`，分支 `panel-xiaomi-umi`）

| 文件 | 内容 |
|---|---|
| `0001-drm-panel-xiaomi-umi.patch` | 内核补丁：新增 `drivers/gpu/drm/panel/panel-xiaomi-umi.c`（931 行）+ Kconfig/Makefile。**基于 v6.18 的 panel Kconfig/Makefile 生成**，能直接 `git am` |
| `misaka-pull-1.patch` | PR 分支那一个 commit 的完整导出（= `git format-patch -1`），含 DT/dtsi/文档 + 上面的内核补丁文件 |
| `PR-body.md` | PR 正文（`gh pr edit 1 --body-file` 用的就是它） |

## 这条 PR 能给他们什么

他们的仓库目前是 **`simple-framebuffer`（ABL 留下的 cont-splash）**，面板节点
在 `sm8250-xiaomi-umi-common.dtsi` 里整段被注释掉（他们自己也标了
`//TODO: ... DSC CMD Mode ... msm#42`）。我们这套驱动在实机上跑通了：

- 1080×2340 命令模式 + **DSC 1.1**（`dsc-cmd-mode`），652 字节 on 序列
- `bl_ctrl_dcs` 背光，亮度 1..2047，`/sys/class/backlight/umi-panel`
- 息屏再亮、**面板级 repower**（`echo 1 > …/repower` 重发 on 序列，偶发
  开机黑屏不用重启）
- 数据驱动：驱动只认 `xiaomi,umi-panel`，时序/DCS 序列/panel-id 全在 DT 里，
  所以一个驱动覆盖 umi 的全部变体（华星 `42` / 三星 `38` / …）；本 PR 里
  的 dtsi 是**本机 CSOT `j2_mp_42_02_0b`** 那一份
- 附带 `dsi` 调试节点：可以直接往 DSI 发原始 DCS 包，做面板实验不用重编内核

实测环境：小米 10（umi / M2008J2C，SM8250，**CSOT（华星光电）
`j2_mp_42_02_0b`** 面板），主线 6.12.94。日志与踩坑记录在
<https://github.com/colorgarden/umi-mainline>（`docs/DISPLAY.md`、
`docs/TOUCH.md`）。

## 怎么提

已经提好了（`gh pr create` 成功，输出 `https://github.com/misaka-link/umi-linux/pull/1`），
下面是重现步骤，供以后改版/重开 PR 用：

```sh
# 1. fork + clone
gh repo fork misaka-link/umi-linux --clone
cd umi-linux

# 2. 建分支并应用补丁（misaka-pull-1.patch 是已经提上去的完整 commit；
#    只想要内核部分就单独 git am 0001-drm-panel-xiaomi-umi.patch）
git checkout -b panel-xiaomi-umi
git am /path/to/misaka-pull-1.patch

# 3. 推到自己的 fork
git push -u origin panel-xiaomi-umi

# 4. 开 PR（正文用下面那段）
gh pr create --repo misaka-link/umi-linux \
  --title "drm/panel: 小米 10（umi）AMOLED 面板驱动 + DT 打开 mdss/DSI" \
  --body-file PR-body.md
```

没有 `gh` 的话：`git push` 之后 GitHub 会直接给出 “Compare & pull request” 的链接。

## PR 正文（可直接粘）

```markdown
### 这个 PR 做什么

给 umi 补一份主线风格的 DRM 面板驱动，替换目前的 `simple-framebuffer`：

1. `drivers/gpu/drm/panel/panel-xiaomi-umi.c`：数据驱动的 AMOLED 面板驱动
   （compatible `xiaomi,umi-panel`），命令模式 + DSC 1.1，背光走
   `bl_ctrl_dcs`（1..2047），带 `repower` / `kick` / `dsi` 三个调试节点。
2. `dt/xiaomi-umi-panels.dtsi`：本机 **CSOT `j2_mp_42_02_0b`** 的时序与
   652 字节 DCS on/off 序列（从原厂 DTB 生成）；其它 21 个变体用生成器
   重新导出，驱动不用改。
3. `dt/sm8250-xiaomi-umi-common.dtsi`：把原来注释掉的
   `&mdss` / `&mdss_dsi0` / `&mdss_dsi0_phy` 真正打开，接上面板节点。
4. `docs/05-面板驱动.md`：选项、换面板、已知问题。

### 为什么之前是注释的

仓库里那段注释指向 [msm#42](https://gitlab.freedesktop.org/drm/msm/-/issues/42)
（DSC + cmd mode 的 tearing）。实测在 6.12 上面板能正常显示、能调亮度、
能息屏再亮，DSC 参数按原厂 DT 配置即可；偶发开机黑屏用 `repower` 重发 on
序列就能恢复（不需要重启）。

### 测试

- 设备：小米 10（umi / SM8250 / **CSOT（华星光电）** `j2_mp_42_02_0b` 面板）
- 内核：主线 6.12.94；本 PR 的 Kconfig/Makefile 段是基于 v6.18 生成的
- 结果：fbcon 在 1080×2340 下正常，`/sys/class/backlight/umi-panel`
  亮度 1..2047 生效，息屏再亮正常，`repower` 能把黑屏救回来

### 注意

- 需要 `CONFIG_DRM_MSM=y` + `CONFIG_DRM_PANEL_XIAOMI_UMI=y`；注意
  `QCOM_OCMEM=m` 之类的依赖会把 `DRM_MSM` 悄悄降成 `=m`。
- 驱动在 6.12 上验证；6.18 的 panel API 没有大改，但建议先
  `make drivers/gpu/drm/panel/` 编一遍。有问题我来改。
- 触摸不在本 PR 范围内。
```

## 我们自己这边的对照信息

同一个驱动在我们仓库里的位置（如果要同步维护两份）：

- 驱动源码：`patches/panel-xiaomi-umi.c`（`scripts/build.sh` 会拷进内核树）
- 面板数据：`dts/xiaomi-umi-panels.dtsi`（`tools/gen-panel-dts.py` 生成）
- DT 接线：`dts/sm8250-xiaomi-umi.dts` 末尾 `#include "xiaomi-umi-panels.dtsi"`
- 说明文档：`docs/DISPLAY.md`
