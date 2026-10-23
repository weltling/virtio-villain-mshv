/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VV_MSHV_TEST_H
#define VV_MSHV_TEST_H

#include <stdint.h>
#include <stddef.h>
#include <linux/types.h>
#include <sys/ioctl.h>
#include "lib/test_runner.h"

#if !defined(__x86_64__)
#error "The MSHV test ABI supports x86_64 only"
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

/* Arbitrary GPR test patterns, not Hyper-V ABI constants. */
#define VV_GPR_SEED_ASCENDING UINT64_C(0x0123456789abcdef)
#define VV_GPR_SEED_DESCENDING UINT64_C(0xfedcba9876543210)
#define VV_GPR_SEED_LIFECYCLE UINT64_C(0x123456789abcdef0)
#define VV_GPR_SEED_VP_FIRST UINT64_C(0x1020304050607080)
#define VV_GPR_PATTERN_EDGE_BITS UINT64_C(0x8000000000000001)
#define VV_GPR_REGISTER_STRIDE UINT64_C(0x1111111111111111)
#define VV_GPR_CYCLE_XOR UINT64_C(0x0101010101010101)
#define VV_GPR_LOW32_MASK UINT64_C(0x00000000ffffffff)

#define VV_GPR_SEED_MISMATCHED_ROUTING UINT64_C(0x1122334455667788)
#define VV_GPR_SEED_INVALID_DESCRIPTOR UINT64_C(0x2233445566778899)
#define VV_GPR_SEED_NULL_POINTER_FAULTS UINT64_C(0x33445566778899aa)
#define VV_GPR_SEED_CREATION_BOUNDARIES UINT64_C(0x445566778899aabb)
#define VV_GPR_SEED_UNINITIALIZED_PARTITION UINT64_C(0x5566778899aabbcc)
#define VV_GPR_SEED_VP_CPUID UINT64_C(0x66778899aabbccdd)
#define VV_GPR_SEED_VP_STATE UINT64_C(0x778899aabbccddee)
#define VV_GPR_SEED_PARTITION_PROPERTY UINT64_C(0x8899aabbccddeeff)
#define VV_GPR_SEED_GUEST_MEMORY UINT64_C(0x99aabbccddeeff00)
#define VV_GPR_SEED_IRQ_EVENTFD UINT64_C(0xaabbccddeeff0011)

#define VV_GPR_SEED_INVALID_COUNT UINT64_C(0x1111222233334444)
#define VV_GPR_SEED_NULL_ARGUMENT UINT64_C(0x5555666677778888)
#define VV_GPR_SEED_NULL_REGISTERS UINT64_C(0x9999aaaabbbbcccc)
#define VV_GPR_SEED_FORBIDDEN_REGISTER UINT64_C(0xdeadbeef12345678)

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

#include "lib/ioctls.h"

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
test_result_t mshv_set_gprs(struct mshv_fixture *f, unsigned count, uint64_t seed);
test_result_t mshv_check_gprs(struct mshv_fixture *f, unsigned count, uint64_t seed);
test_result_t mshv_roundtrip(struct mshv_fixture *f, unsigned count, uint64_t seed);
test_result_t mshv_expect_ioctl(int fd, unsigned long request, void *arg,
                              const char *operation, int expected_errno);

#endif
