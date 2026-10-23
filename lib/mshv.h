/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VV_MSHV_TEST_H
#define VV_MSHV_TEST_H

#include <stdint.h>
#include <stddef.h>
#include <linux/types.h>
#include <sys/ioctl.h>
#include "lib/test_runner.h"

#if !defined(__x86_64__)
#error "The initial MSHV contract supports x86_64 only"
#endif

enum vv_cpuid_leaf {
    VV_X86_CPUID_FEATURES = 0x00000001,
    HYPERV_CPUID_VENDOR_AND_MAX_FUNCTIONS = 0x40000000,
    HYPERV_CPUID_INTERFACE = 0x40000001,
    HYPERV_CPUID_FEATURES = 0x40000003,
};

/* CPUID(1).ECX, named as in the selected kernel's hvgdk_mini.h. */
#define HYPERV_HYPERVISOR_PRESENT_BIT UINT32_C(0x80000000)

/* HYPERV_CPUID_INTERFACE.EAX encodes little endian ASCII "Hv#1". */
#define VV_HYPERV_INTERFACE_HV1_SIGNATURE UINT32_C(0x31237648)

/* HYPERV_CPUID_FEATURES.EBX privilege bits from hvgdk_mini.h. */
enum vv_hyperv_partition_privilege {
    HV_CREATE_PARTITIONS = 1U << 0,
    HV_ISOLATION = 1U << 22,
};

#define VV_MSHV_PARTITION_FLAGS_NONE UINT64_C(0)

/* TLFS register association: MBZ fields and a 128-bit value slot. */
struct hv_register_assoc {
    uint32_t name;
    uint32_t reserved1;
    uint64_t reserved2;
    union {
        uint64_t words[2];
        uint64_t reg64;
    } value;
} __attribute__((packed));

#include "contract.h"

_Static_assert(sizeof(struct hv_register_assoc) == 32, "register association ABI");
_Static_assert(offsetof(struct hv_register_assoc, value) == 16, "register value ABI");
_Static_assert(sizeof(struct mshv_vp_registers) == 16, "register ioctl ABI");
_Static_assert(sizeof(struct mshv_create_partition) == 16, "partition ioctl ABI");
_Static_assert(sizeof(struct mshv_create_vp) == 4, "VP ioctl ABI");

enum vv_hyperv_register_name {
    VV_RAX = 0x00020000,
    VV_RCX = 0x00020001,
    VV_RDX = 0x00020002,
    VV_RBX = 0x00020003,
    VV_EXPLICIT_SUSPEND = 0,
    VV_INTERCEPT_SUSPEND = 1,
};

struct mshv_fixture {
    int device;
    int partition;
    int vp;
};

#define REGISTER_MSHV_TEST(name, func, description) \
    VV_REGISTER_TEST(mshv_registry, name, func, description)

extern const struct vv_test_entry __start_mshv_registry[];
extern const struct vv_test_entry __stop_mshv_registry[];

int mshv_preflight(void);
void mshv_init_context(void *context);
test_result_t mshv_cleanup_context(void *context);
test_result_t mshv_create(struct mshv_fixture *f);
test_result_t mshv_check_fd(int fd, const char *operation, ...)
    __attribute__((format(printf, 2, 3)));
test_result_t mshv_close(int *fd, const char *operation);
test_result_t mshv_cleanup(struct mshv_fixture *f);
test_result_t mshv_roundtrip(struct mshv_fixture *f, unsigned count, uint64_t seed);
test_result_t mshv_expect_ioctl(int fd, unsigned long request, void *arg,
                              const char *operation, int expected_errno);

#endif
