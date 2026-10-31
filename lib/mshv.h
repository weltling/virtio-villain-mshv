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
    HYPERV_CPUID_IMPLEMENTATION_LIMITS = 0x40000005,
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

struct hv_x64_segment_register {
    uint64_t base;
    uint32_t limit;
    uint16_t selector;
    uint16_t attributes;
};

union hv_register_value {
    uint64_t words[2];
    uint64_t reg64;
    struct hv_x64_segment_register segment;
} __attribute__((aligned(16)));

/* TLFS register association: MBZ fields and a 128-bit value slot. */
struct hv_register_assoc {
    uint32_t name;
    uint32_t reserved1;
    uint64_t reserved2;
    union hv_register_value value;
} __attribute__((packed, aligned(16)));

struct hv_vp_register_header {
    uint64_t partition_id;
    uint32_t vp_index;
    uint8_t input_vtl;
    uint8_t reserved[3];
};

struct hv_input_set_partition_property {
    uint64_t partition_id;
    uint64_t property_code;
    uint64_t property_value;
};

struct hv_input_translate_gva {
    uint64_t partition_id;
    uint32_t vp_index;
    uint32_t reserved;
    uint64_t flags;
    uint64_t gva_page;
};

struct hv_output_translate_gva {
    uint64_t result;
    uint64_t gpa_page;
};

enum hv_translate_gva_result_code {
    HV_TRANSLATE_GVA_SUCCESS = 0,
    HV_TRANSLATE_GVA_PAGE_NOT_PRESENT = 1,
    HV_TRANSLATE_GVA_PRIVILEGE_VIOLATION = 2,
};

#include "lib/ioctls.h"

_Static_assert(sizeof(union hv_register_value) == 16, "register value size ABI");
_Static_assert(_Alignof(union hv_register_value) == 16, "register value alignment ABI");
_Static_assert(sizeof(struct hv_register_assoc) == 32, "register association ABI");
_Static_assert(offsetof(struct hv_register_assoc, value) == 16, "register value ABI");
_Static_assert(sizeof(struct mshv_vp_registers) == 16, "register ioctl ABI");
_Static_assert(sizeof(struct mshv_create_partition) == 16, "partition ioctl ABI");
_Static_assert(sizeof(struct mshv_create_vp) == 4, "VP ioctl ABI");
_Static_assert(sizeof(struct mshv_root_hvcall) == 32, "hypercall ioctl ABI");
_Static_assert(offsetof(struct mshv_root_hvcall, in_ptr) == 16, "hypercall input pointer ABI");
_Static_assert(MSHV_ROOT_HVCALL == 0xc020b807UL, "hypercall request ABI");
_Static_assert(sizeof(struct mshv_translate_gva) == 32, "translation ioctl ABI");
_Static_assert(MSHV_TRANSLATE_GVA == 0xc020b8f2UL, "translation request ABI");
_Static_assert(sizeof(struct hv_vp_register_header) == 16, "register hypercall header ABI");
_Static_assert(sizeof(struct hv_input_set_partition_property) == 24, "property hypercall ABI");
_Static_assert(sizeof(struct hv_input_translate_gva) == 32, "translation hypercall input ABI");
_Static_assert(sizeof(struct hv_output_translate_gva) == 16, "translation hypercall output ABI");
_Static_assert(sizeof(enum hv_translate_gva_result_code) == 4, "translation result ABI");

enum vv_hyperv_register_name {
    VV_RAX = 0x00020000,
    VV_RCX = 0x00020001,
    VV_RDX = 0x00020002,
    VV_RBX = 0x00020003,
    VV_RFLAGS = 0x00020011,
    VV_XMM0 = 0x00030000,
    VV_XMM1 = 0x00030001,
    VV_CR0 = 0x00040000,
    VV_CR3 = 0x00040002,
    VV_CR4 = 0x00040003,
    VV_CS = 0x00060001,
    VV_EFER = 0x00080001,
    VV_VP_INDEX = 0x00090003,
    VV_EXPLICIT_SUSPEND = 0,
    VV_INTERCEPT_SUSPEND = 1,
};

enum vv_hyperv_hypercall_code {
    HVCALL_SET_PARTITION_PROPERTY = 0x0045,
    HVCALL_GET_VP_REGISTERS = 0x0050,
    HVCALL_SET_VP_REGISTERS = 0x0051,
    HVCALL_TRANSLATE_VIRTUAL_ADDRESS = 0x0052,
};

enum vv_hyperv_partition_property {
    HV_PARTITION_PROPERTY_PRIVILEGE_FLAGS = 0x00010000,
    HV_PARTITION_PROPERTY_SYNTHETIC_PROC_FEATURES = 0x00010001,
};

#define VV_HV_FEATURE_HYPERVISOR_PRESENT (UINT64_C(1) << 0)
#define VV_HV_FEATURE_HV1 (UINT64_C(1) << 1)
#define VV_HV_FEATURE_SYNIC (UINT64_C(1) << 4)
#define VV_HV_FEATURE_VP_INDEX (UINT64_C(1) << 8)
#define VV_TLFS_BASIC_FEATURES \
    (VV_HV_FEATURE_HYPERVISOR_PRESENT | VV_HV_FEATURE_HV1 | VV_HV_FEATURE_VP_INDEX)
#define VV_HV_CPUID_ACCESS_VP_INDEX (UINT32_C(1) << 6)

#define HV_TRANSLATE_GVA_VALIDATE_READ UINT64_C(0x0001)
#define HV_TRANSLATE_GVA_VALIDATE_WRITE UINT64_C(0x0002)
/* MSHV extends the TLFS 6.0b flags with explicit supervisor access context. */
#define HV_TRANSLATE_GVA_SUPERVISOR_ACCESS UINT64_C(0x0040)

enum vv_hvcall_expectation {
    VV_HVCALL_SUCCESS,
    VV_HVCALL_REJECTED,
};

struct mshv_fixture {
    int device;
    int partition;
    int vp;
};

#define TLFS_SPEC_V6_0B "6.0b"

#define REGISTER_MSHV_TEST(name, func, description, specver, sect) \
    VV_REGISTER_TEST_SPEC(mshv_registry, name, func, description, specver, sect)

extern const struct vv_test_entry __start_mshv_registry[];
extern const struct vv_test_entry __stop_mshv_registry[];

int mshv_preflight(void);
void mshv_init_context(void *context);
test_result_t mshv_cleanup_context(void *context);
test_result_t mshv_create(struct mshv_fixture *f);
test_result_t mshv_create_configured(struct mshv_fixture *f, uint64_t flags, uint64_t features);
test_result_t mshv_check_fd(int fd, const char *operation, ...)
    __attribute__((format(printf, 2, 3)));
test_result_t mshv_close(int *fd, const char *operation);
test_result_t mshv_cleanup(struct mshv_fixture *f);
test_result_t mshv_set_gprs(struct mshv_fixture *f, unsigned count, uint64_t seed);
test_result_t mshv_check_gprs(struct mshv_fixture *f, unsigned count, uint64_t seed);
test_result_t mshv_roundtrip(struct mshv_fixture *f, unsigned count, uint64_t seed);
test_result_t mshv_get_registers(int fd, uint32_t vp_index, const uint32_t *names,
                                 union hv_register_value *values, unsigned count);
test_result_t mshv_set_registers(int fd, uint32_t vp_index,
                                 const struct hv_register_assoc *regs, unsigned count);
test_result_t mshv_expect_hvcall(int fd, struct mshv_root_hvcall *args,
                                 const char *operation, enum vv_hvcall_expectation expected);
test_result_t mshv_expect_ioctl(int fd, unsigned long request, void *arg,
                              const char *operation, int expected_errno);

#endif
