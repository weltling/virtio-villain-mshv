/* SPDX-License-Identifier: Apache-2.0 */
/*
 * TL0004: Hv#1 discovery and child feature exposure.
 *
 * TLFS 6.0b section 2.4 defines the Hv#1 interface, CPUID leaf range
 * and reported features. Section 2.2 defines the hypervisor present bit.
 * Requires child synthetic features configurable before initialization.
 * Check two child policies without comparing child CPUID with parent CPUID.
 */
#include "lib/mshv.h"

static test_result_t query_cpuid(struct mshv_fixture *f, uint32_t function,
                                 struct mshv_get_vp_cpuid_values *args)
{
    *args = (struct mshv_get_vp_cpuid_values){
        .function = function,
        .eax = UINT32_C(0xa5a5a5a5),
        .ebx = UINT32_C(0xa5a5a5a5),
        .ecx = UINT32_C(0xa5a5a5a5),
        .edx = UINT32_C(0xa5a5a5a5),
    };
    return mshv_expect_ioctl(f->vp, MSHV_GET_VP_CPUID_VALUES, args, "query child CPUID", 0);
}

static test_result_t cpuid(struct mshv_fixture *f)
{
    const uint64_t policies[] = {
        VV_HV_FEATURE_HYPERVISOR_PRESENT | VV_HV_FEATURE_HV1,
        VV_TLFS_BASIC_FEATURES,
    };
    struct mshv_get_vp_cpuid_values args;

    for (unsigned i = 0; i < sizeof(policies) / sizeof(policies[0]); ++i) {
        if (mshv_create_configured(f, VV_MSHV_PARTITION_FLAGS_NONE, policies[i]) != TEST_PASS ||
            query_cpuid(f, VV_X86_CPUID_FEATURES, &args) != TEST_PASS)
            return TEST_FAIL;
        if (!(args.ecx & HYPERV_HYPERVISOR_PRESENT_BIT))
            TFAIL("child CPUID.1: expected hypervisor present, actual ECX=0x%x", args.ecx);
        if (query_cpuid(f, HYPERV_CPUID_VENDOR_AND_MAX_FUNCTIONS, &args) != TEST_PASS)
            return TEST_FAIL;
        if (args.eax < HYPERV_CPUID_IMPLEMENTATION_LIMITS)
            TFAIL("child CPUID maximum: expected at least 0x%x, actual 0x%x",
                  HYPERV_CPUID_IMPLEMENTATION_LIMITS, args.eax);
        if (query_cpuid(f, HYPERV_CPUID_INTERFACE, &args) != TEST_PASS)
            return TEST_FAIL;
        if (args.eax != VV_HYPERV_INTERFACE_HV1_SIGNATURE)
            TFAIL("child CPUID interface: expected Hv#1 0x%x, actual 0x%x",
                  VV_HYPERV_INTERFACE_HV1_SIGNATURE, args.eax);
        if (query_cpuid(f, HYPERV_CPUID_FEATURES, &args) != TEST_PASS)
            return TEST_FAIL;
        uint32_t expected_index = policies[i] & VV_HV_FEATURE_VP_INDEX ?
                                  VV_HV_CPUID_ACCESS_VP_INDEX : 0;
        if ((args.eax & VV_HV_CPUID_ACCESS_VP_INDEX) != expected_index)
            TFAIL("child CPUID VP index feature: expected 0x%x, actual EAX=0x%x",
                  expected_index, args.eax);
        if (args.ebx & HV_CREATE_PARTITIONS)
            TFAIL("child CPUID privileges: expected no CreatePartitions, actual EBX=0x%x",
                  args.ebx);
        if (mshv_cleanup(f) != TEST_PASS)
            return TEST_FAIL;
    }
    return TEST_PASS;
}

REGISTER_MSHV_TEST(TL0004, cpuid,
                   "Hv#1 discovery and configured child CPUID features",
                   TLFS_SPEC_V6_0B, "2.4");
