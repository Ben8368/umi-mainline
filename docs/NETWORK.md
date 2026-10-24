# USB 网络（RNDIS）与 SSH

> 目标：给 umi 一条**比串口快几百倍**的控制通道，传 boot.img 不用再按键刷机。
>
> 结果：Windows 直接冒出「Remote NDIS Compatible Device」，`ssh root@192.168.42.1` 通，
> `scp` 一个 16 MB 的 boot.img 只要 1.3 秒（≈12 MB/s，串口是 0.011 MB/s）。

---

## 1. 为什么选 RNDIS

- 内核 `CONFIG_USB_CONFIGFS_RNDIS=y` 已经开了
- Windows 自带 `netrndis.inf`，不需要装第三方驱动
- 手机端就是一张普通网卡（`usb0`），Arch 的 `systemd-networkd` 直接接管

## 2. 三个必须踩对的点（都踩过）

### 2.1 `class` 要写**裸十六进制**，不能带 `0x`

`f_rndis` 默认把接口宣告成 `02/06/00`（CDC-ECM 风格），Windows 对它没有任何驱动。
RNDIS 应该是 `ef/04/01`。

但 configfs 的 setter 是这样写的：

```c
/* drivers/usb/gadget/function/u_ether_configfs.h */
if (sscanf(page, "%02hhx", &val) > 0) {
	opts->_n_ = val;
	ret = len;
}
```

`%02hhx` **只读两个十六进制字符**。写 `echo 0xef` 时它读到的是 `0x` → **0**，
于是属性变成 `00/00/00`，Windows 那边的 compatible-id 变成
`USB\Class_00&SubClass_00&Prot_00`，比以前更没救。

正确写法：

```sh
echo ef > $G/functions/rndis.usb0/class
echo 04 > $G/functions/rndis.usb0/subclass
echo 01 > $G/functions/rndis.usb0/protocol
```

改完之后 Windows 看到的 compatible-id 就是
`USB\Class_ef&SubClass_04&Prot_01` —— **自带 `netrndis.inf` 正是匹配这个**，
连 MS OS Descriptor 都不需要。

### 2.2 `os_desc` 在 **function** 里，不在 gadget 里

```
functions/rndis.usb0/os_desc/interface.rndis/     ← 这个存在（f_rndis 自己建的）
os_desc/interface.rndis/                          ← 这个永远建不出来
```

gadget 级 `os_desc` 的 `config_item_type` **没有 `ct_group_ops`**：

```c
/* drivers/usb/gadget/configfs.c:1274 */
static const struct config_item_type os_desc_type = {
	.ct_item_ops	= &os_desc_ops,
	.ct_attrs	= os_desc_attrs,
	.ct_owner	= THIS_MODULE,
};          /* 没有 .ct_group_ops → mkdir 一律 EPERM */
```

所以在 gadget 的 `os_desc/` 下面 `mkdir interface.rndis` 只会得到
`Operation not permitted`。要写的是 **function 里那份**：

```sh
echo RNDIS   > $G/functions/rndis.usb0/os_desc/interface.rndis/compatible_id
echo 5162001 > $G/functions/rndis.usb0/os_desc/interface.rndis/sub_compatible_id
ln -sf $G/configs/c.1 $G/functions/rndis.usb0/os_desc/interface.rndis/config
```

（有 `class=ef/04/01` 之后这段其实是可选的双保险。）

### 2.3 所有配置必须在 **UDC 绑定之前**完成

gadget 一旦 `echo $UDC > UDC`，这些属性就锁死了：写 `class` 返回 0 但读回来不变。
运行时改的唯一办法是先解绑——**实测解绑再重绑会把 UDC 弄挂，串口和网络同时消失，
只能长按电源重启**。所以全部写进 initramfs 的 init 脚本，开机就配好。

### 2.4 Windows 会按 VID/PID 缓存描述符

改了 `class` 之后，`1d6b:0104` 这个 ID 上缓存过旧描述符，Windows 不一定会重新读。
所以顺手把 product id 提到 **`0x0105`**，强制它干净地重新枚举一次。

## 3. Windows 侧

设备管理器里出现 **「Remote NDIS Compatible Device」**（Class = Net，Status = OK），
`Get-NetAdapter` 能看到「以太网 2」。

**手机端没有 DHCP 服务**，所以电脑要手动配地址：

```powershell
$if = Get-NetAdapter -IncludeHidden | Where-Object { $_.InterfaceDescription -match 'Remote NDIS' }
New-NetIPAddress -InterfaceIndex $if.ifIndex -IPAddress 192.168.42.2 -PrefixLength 24
Test-Connection 192.168.42.1        # → True，rtt < 1 ms
```

手机端 `usb0` 是 `192.168.42.1/24`，由 Arch 的
`/etc/systemd/network/10-usb0.network` 配置。

## 4. SSH

Arch 镜像里 `sshd` 已 enable，`root` 密码 `umi`，`PermitRootLogin yes`。

免密登录（把公钥写进 `/root/.ssh/authorized_keys`，串口一条命令即可）：

```powershell
$pub = (Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub").Trim()
# 通过串口写入手机上 /root/.ssh/authorized_keys
```

然后：

```powershell
ssh root@192.168.42.1 "uname -a"
```

## 5. 日常操作流程（不再需要按键进 fastboot）

```powershell
# 改内核/dtb 之后
scp out\boot-umi-xxx.img root@192.168.42.1:/tmp/
ssh root@192.168.42.1 "dd if=/tmp/boot.img of=/dev/sde50 bs=4M && sync && reboot"
```

- `boot` 分区在 mainline 里是 `/dev/sde50`
- `/tmp` 是 tmpfs 3.7 GB，传 16 MB 的 boot.img 只要 **1.3 s**
- 传 6 GB 的 rootfs 会失败（`write remote: Failure`，tmpfs 装不下），
  大镜像仍然走 TWRP + adb 分块 dd（见 `docs/WIFI.md` 末尾）

## 6. 实测数据

| 项 | 结果 |
|---|---|
| 设备 | `USB\VID_1D6B&PID_0105&MI_00` → Remote NDIS Compatible Device |
| 网卡 | 以太网 2，`192.168.42.2/24` |
| ping | 4/4，rtt < 1 ms |
| TCP 22 | 通 |
| `scp` 16 MiB | **1.3 s**（≈12 MB/s） |
| `scp` 3.9 GiB | 180 s 后失败（tmpfs 满），速度 ≈21 MB/s |
| `systemctl --failed` | 0 units |
