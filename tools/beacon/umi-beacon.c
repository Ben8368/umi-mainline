// SPDX-License-Identifier: GPL-2.0
/*
 * umi-beacon.c - very early boot beacon for Xiaomi Mi 10 (umi) bring-up.
 * Out-of-tree, inject with scripts/add-beacon.sh, remove with remove-beacon.sh.
 *
 * NOTE: every string this driver prints is plain ASCII on purpose - the
 * framebuffer console and the drm_panic screen use the VGA font, which has no
 * CJK glyphs.
 *
 * It solves two problems:
 *
 * 1) The window where the screen is guaranteed to be blank.
 *    The only thing that can put text on screen is fbcon, and fbcon binds when
 *    simpledrm probes, at device_initcall. Anything that hangs between
 *    start_kernel and device_initcall (memory, clocks, pinctrl, regulators,
 *    UFS, ...) produces no output at all. So this driver paints the whole
 *    cont-splash framebuffer a solid color at four initcall stages:
 *
 *        black           did not reach postcore_initcall (or ABL blanked the panel)
 *        blue  0x0000FF  postcore_initcall
 *        cyan  0x00FFFF  arch_initcall
 *        green 0x00FF00  subsys_initcall
 *        yellow0xFFFF00  fs_initcall
 *        text console    after device_initcall (fbcon took over)
 *
 * 2) When the screen itself cannot be trusted (ABL may blank the panel).
 *    Colors need eyes. So each stage also writes a progress marker into the
 *    LAST 4 KB of the cont-splash reserved region (nobody uses it, and it
 *    survives a warm reset). On the next boot, postcore reads it back and
 *    prints it:
 *
 *        UMI-BEACON: previous boot reached stage 4 = fs_initcall (marker v1, boot #3)
 *
 *    So "how far did the last boot get" is available WITHOUT any screen: that
 *    line ends up in dmesg, on the USB serial port and in pstore.
 */
#include <linux/init.h>
#include <linux/io.h>
#include <linux/jiffies.h>
#include <linux/kernel.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/slab.h>
#include <linux/string.h>

#define UMI_FB_FALLBACK_ADDR	0x9c000000UL
#define UMI_FB_FALLBACK_SIZE	0x2300000UL
#define UMI_BEACON_CHUNK	(256 * 1024)
#define UMI_MARKER_OFFSET	0x1000	/* last 4 KB of the reserved region */

static void __iomem *umi_fb;
static resource_size_t umi_fb_size;
static void __iomem *umi_marker;
static u32 umi_boot_count;

/* ARGB8888 */
#define UMI_C_BLUE	0x000000ff
#define UMI_C_CYAN	0x0000ffff
#define UMI_C_GREEN	0x0000ff00
#define UMI_C_YELLOW	0x00ffff00

#define UMI_MARKER_MAGIC	0x554d4942u	/* "UMIB" */
#define UMI_MARKER_VERSION	1

#define UMI_STAGE_NONE		0
#define UMI_STAGE_POSTCORE	1
#define UMI_STAGE_ARCH		2
#define UMI_STAGE_SUBSYS	3
#define UMI_STAGE_FS		4
#define UMI_STAGE_DEVICE	5
#define UMI_STAGE_LATE		6

static const char * const umi_stage_names[] = {
	"none (fresh power-on, or the last boot did not reach postcore)",
	"postcore_initcall",
	"arch_initcall",
	"subsys_initcall",
	"fs_initcall",
	"device_initcall (fbcon should own the screen now)",
	"late_initcall",
};

/* Marker lives in the last 4 KB of the framebuffer region - unused, and not
 * cleared by a warm reset. */
static void __iomem *umi_marker_addr(void __iomem *fb, resource_size_t size)
{
	if (size <= UMI_MARKER_OFFSET)
		return NULL;
	return (void __iomem *)((u8 __iomem *)fb + size - UMI_MARKER_OFFSET);
}

static void umi_marker_write(u32 stage)
{
	u8 __iomem *m = umi_marker;

	if (!m)
		return;

	writel(UMI_MARKER_MAGIC, m + 0x00);
	writel(UMI_MARKER_VERSION, m + 0x04);
	writel(stage, m + 0x08);
	writel(umi_boot_count, m + 0x0c);
	writeq(jiffies, m + 0x10);
	wmb();
}

static void umi_marker_read(void)
{
	u8 __iomem *m = umi_marker;
	u32 magic, ver, stage, boots;
	u64 stamp;

	if (!m)
		return;

	magic = readl(m + 0x00);
	if (magic != UMI_MARKER_MAGIC) {
		pr_info("UMI-BEACON: no previous marker (fresh power-on, or the last boot did not reach postcore)\n");
		umi_boot_count = 1;
		return;
	}

	ver = readl(m + 0x04);
	stage = readl(m + 0x08);
	boots = readl(m + 0x0c);
	stamp = readq(m + 0x10);
	rmb();

	umi_boot_count = boots + 1;

	if (stage > UMI_STAGE_LATE)
		stage = UMI_STAGE_NONE;

	pr_info("UMI-BEACON: previous boot reached stage %u = %s (marker v%u, boot #%u, jiffies=%llu)\n",
		stage, umi_stage_names[stage], ver, boots, stamp);
}

static int __init umi_beacon_setup(void)
{
	struct device_node *np;
	struct resource res = { };

	np = of_find_node_by_path("/chosen");
	if (np) {
		struct device_node *fb = of_get_compatible_child(np, "simple-framebuffer");

		if (fb) {
			if (!of_address_to_resource(fb, 0, &res))
				umi_fb_size = resource_size(&res);
			of_node_put(fb);
		}
		of_node_put(np);
	}

	if (!res.start) {
		np = of_find_compatible_node(NULL, NULL, "simple-framebuffer");
		if (np) {
			if (!of_address_to_resource(np, 0, &res))
				umi_fb_size = resource_size(&res);
			of_node_put(np);
		}
	}

	if (!res.start) {
		res.start = UMI_FB_FALLBACK_ADDR;
		umi_fb_size = UMI_FB_FALLBACK_SIZE;
	}
	if (!umi_fb_size)
		umi_fb_size = UMI_FB_FALLBACK_SIZE;

	umi_fb = ioremap(res.start, umi_fb_size);
	if (!umi_fb) {
		pr_err("UMI-BEACON: ioremap(0x%llx, 0x%llx) failed\n",
		       (unsigned long long)res.start, (unsigned long long)umi_fb_size);
		return -ENOMEM;
	}

	umi_marker = umi_marker_addr(umi_fb, umi_fb_size);

	pr_info("UMI-BEACON: framebuffer 0x%llx size 0x%llx, marker area %s\n",
		(unsigned long long)res.start, (unsigned long long)umi_fb_size,
		umi_marker ? "OK" : "unavailable");
	return 0;
}

static void umi_beacon_paint(u32 color, u32 stage)
{
	size_t todo, off = 0;
	void *buf;

	umi_marker_write(stage);

	if (!umi_fb)
		return;

	pr_info("UMI-BEACON: reached %s (painting 0x%06x)\n", umi_stage_names[stage], color);

	/*
	 * Only paint the first 16 MB: 1080x2340x4 = 9.6 MB, plus margin.
	 * One buffer + memcpy_toio is much faster than 10 million writel().
	 */
	todo = min_t(size_t, umi_fb_size, 16UL * 1024 * 1024);

	buf = kmalloc(UMI_BEACON_CHUNK, GFP_KERNEL);
	if (buf) {
		u32 *p = buf;
		size_t i, n = UMI_BEACON_CHUNK / sizeof(u32);

		for (i = 0; i < n; i++)
			p[i] = color;

		while (off < todo) {
			size_t len = min(UMI_BEACON_CHUNK, todo - off);

			memcpy_toio((u8 __iomem *)umi_fb + off, buf, len);
			off += len;
		}
		kfree(buf);
	} else {
		u32 __iomem *p = umi_fb;
		size_t i, n = todo / sizeof(u32);

		for (i = 0; i < n; i++)
			writel(color, p + i);
	}
	mb();
}

static int __init umi_beacon_postcore(void)
{
	if (umi_beacon_setup())
		return 0;
	umi_marker_read();
	umi_beacon_paint(UMI_C_BLUE, UMI_STAGE_POSTCORE);
	return 0;
}
postcore_initcall(umi_beacon_postcore);

static int __init umi_beacon_arch(void)
{
	umi_beacon_paint(UMI_C_CYAN, UMI_STAGE_ARCH);
	return 0;
}
arch_initcall(umi_beacon_arch);

static int __init umi_beacon_subsys(void)
{
	umi_beacon_paint(UMI_C_GREEN, UMI_STAGE_SUBSYS);
	return 0;
}
subsys_initcall(umi_beacon_subsys);

static int __init umi_beacon_fs(void)
{
	umi_beacon_paint(UMI_C_YELLOW, UMI_STAGE_FS);
	return 0;
}
fs_initcall(umi_beacon_fs);

/*
 * After device_initcall fbcon owns the framebuffer, so from here on we only
 * write the marker and print - no more painting.
 */
static int __init umi_beacon_device(void)
{
	umi_marker_write(UMI_STAGE_DEVICE);
	pr_info("UMI-BEACON: reached device_initcall (fbcon should own the screen now)\n");
	return 0;
}
device_initcall(umi_beacon_device);

static int __init umi_beacon_late(void)
{
	umi_marker_write(UMI_STAGE_LATE);
	pr_info("UMI-BEACON: reached late_initcall - kernel init finished\n");
	return 0;
}
late_initcall(umi_beacon_late);
