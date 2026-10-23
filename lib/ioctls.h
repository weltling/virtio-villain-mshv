/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef VV_MSHV_IOCTLS_H
#define VV_MSHV_IOCTLS_H

#include <stddef.h>
#include <stdint.h>
#include <sys/ioctl.h>

/*
 * Stable x86-64 userspace ABI exercised by this suite. Keep these definitions
 * independent of the kernel under test so kernel changes cannot change the
 * requests being tested. Requests without argument structures below retain
 * their expanded codes.
 */
#define VV_MSHV_SUITE_ID "mshv-uapi-v1"

enum {
    MSHV_PT_BIT_LAPIC,
    MSHV_PT_BIT_X2APIC,
    MSHV_PT_BIT_GPA_SUPER_PAGES,
    MSHV_PT_BIT_CPU_AND_XSAVE_FEATURES,
    MSHV_PT_BIT_NESTED_VIRTUALIZATION,
    MSHV_PT_BIT_SMT_ENABLED_GUEST,
    MSHV_PT_BIT_SNP_INJECTION_POLICY0,
    MSHV_PT_BIT_SNP_INJECTION_POLICY1,
    MSHV_PT_BIT_COUNT,
};

enum {
    MSHV_PT_ISOLATION_NONE,
    MSHV_PT_ISOLATION_SNP,
    MSHV_PT_ISOLATION_COUNT,
};

struct mshv_create_partition {
    uint64_t pt_flags;
    uint64_t pt_isolation;
};

struct mshv_create_vp {
    uint32_t vp_index;
};

struct mshv_vp_registers {
    uint32_t count;
    uint32_t padding;
    struct hv_register_assoc *regs;
};

struct mshv_user_mem_region {
    uint64_t size;
    uint64_t guest_pfn;
    uint64_t userspace_addr;
    uint8_t flags;
    uint8_t rsvd[7];
};

struct mshv_user_irqfd {
    int32_t fd;
    int32_t resamplefd;
    uint32_t gsi;
    uint32_t flags;
};

struct mshv_user_ioeventfd {
    uint64_t datamatch;
    uint64_t addr;
    uint32_t len;
    int32_t fd;
    uint32_t flags;
    uint8_t rsvd[4];
};

struct mshv_partition_property {
    uint64_t property_code;
    uint64_t property_value;
};

struct mshv_get_set_vp_state {
    uint8_t type;
    uint8_t rsvd[3];
    uint32_t buf_sz;
    uint64_t buf_ptr;
};

struct mshv_get_vp_cpuid_values {
    uint32_t function;
    uint32_t index;
    uint64_t xfem;
    uint64_t xss;
    uint32_t eax;
    uint32_t ebx;
    uint32_t ecx;
    uint32_t edx;
};

#define MSHV_IOCTL 0xb8
#define MSHV_PT_FLAGS_MASK ((1 << MSHV_PT_BIT_COUNT) - 1)
#define MSHV_VP_MAX_REGISTERS 128

#define MSHV_CREATE_PARTITION _IOW(MSHV_IOCTL, 0x00, struct mshv_create_partition)
#define MSHV_INITIALIZE_PARTITION _IO(MSHV_IOCTL, 0x00)
#define MSHV_CREATE_VP _IOW(MSHV_IOCTL, 0x01, struct mshv_create_vp)
#define MSHV_SET_GUEST_MEMORY _IOW(MSHV_IOCTL, 0x02, struct mshv_user_mem_region)
#define MSHV_IRQFD _IOW(MSHV_IOCTL, 0x03, struct mshv_user_irqfd)
#define MSHV_IOEVENTFD _IOW(MSHV_IOCTL, 0x04, struct mshv_user_ioeventfd)
#define MSHV_SET_MSI_ROUTING 0x4008b805UL
#define MSHV_GET_GPAP_ACCESS_BITMAP 0xc020b806UL
#define MSHV_ROOT_HVCALL 0xc020b807UL
#define MSHV_CREATE_DEVICE 0xc00cb808UL
#define MSHV_MODIFY_GPA_HOST_ACCESS 0x4010b809UL
#define MSHV_IMPORT_ISOLATED_PAGES 0x4010b80aUL
#define MSHV_GET_GPAP_RANGE_ACCESS 0xc028b80bUL
#define MSHV_SCRUB_PARTITION 0x0000b80bUL
#define MSHV_INSTALL_INTERCEPT 0x4010b8f0UL
#define MSHV_ASSERT_INTERRUPT 0x4018b8f1UL
#define MSHV_SET_PARTITION_PROPERTY _IOW(MSHV_IOCTL, 0xf2, struct mshv_partition_property)
#define MSHV_GET_PARTITION_PROPERTY _IOWR(MSHV_IOCTL, 0xf3, struct mshv_partition_property)
#define MSHV_COMPLETE_ISOLATED_IMPORT 0x4d06b8f4UL
#define MSHV_ISSUE_PSP_GUEST_REQUEST 0x4010b8f5UL
#define MSHV_SEV_SNP_AP_CREATE 0x4010b8f6UL
#define MSHV_SIGNAL_EVENT_DIRECT 0xc00cb8f7UL
#define MSHV_POST_MESSAGE_DIRECT 0x4010b8f8UL
#define MSHV_REGISTER_DELIVERABILITY_NOTIFICATIONS 0x4010b8f9UL
#define MSHV_RUN_VP 0x8100b800UL
#define MSHV_GET_VP_STATE _IOWR(MSHV_IOCTL, 0x01, struct mshv_get_set_vp_state)
#define MSHV_SET_VP_STATE _IOWR(MSHV_IOCTL, 0x02, struct mshv_get_set_vp_state)
#define MSHV_TRANSLATE_GVA 0xc020b8f2UL
#define MSHV_GET_VP_REGISTERS _IOWR(MSHV_IOCTL, 0xf0, struct mshv_vp_registers)
#define MSHV_SET_VP_REGISTERS _IOW(MSHV_IOCTL, 0xf1, struct mshv_vp_registers)
#define MSHV_VP_REGISTER_INTERCEPT_RESULT 0x4038b8f3UL
#define MSHV_GET_VP_CPUID_VALUES _IOWR(MSHV_IOCTL, 0xf4, struct mshv_get_vp_cpuid_values)
#define MSHV_READ_GPA 0xc020b8f5UL
#define MSHV_WRITE_GPA 0x4020b8f6UL

enum mshv_ioctl_target {
    VV_IOCTL_DEVICE = 1U << 0,
    VV_IOCTL_PARTITION = 1U << 1,
    VV_IOCTL_VP = 1U << 2,
};

struct mshv_ioctl_entry {
    unsigned long request;
    const char *name;
    unsigned targets;
    /* Zero excludes requests that do not require a pointer argument. */
    int null_errno;
};

extern const struct mshv_ioctl_entry mshv_ioctl_table[];
extern const size_t mshv_ioctl_count;

#endif
