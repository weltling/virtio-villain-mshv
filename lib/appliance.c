/* SPDX-License-Identifier: Apache-2.0 */
#include <cpuid.h>

#include "lib/mshv.h"

int mshv_preflight(void)
{
    unsigned a, b, c, d;
    __cpuid(VV_X86_CPUID_FEATURES, a, b, c, d);
    if (!(c & HYPERV_HYPERVISOR_PRESENT_BIT)) {
        printf("mshv-infra expected Hyper-V parent partition, no hypervisor CPUID bit\n");
        return -1;
    }
    __cpuid(HYPERV_CPUID_VENDOR_AND_MAX_FUNCTIONS, a, b, c, d);
    if (a < HYPERV_CPUID_FEATURES) {
        printf("mshv-infra Hyper-V feature leaf unavailable: max=0x%x\n", a);
        return -1;
    }
    __cpuid(HYPERV_CPUID_INTERFACE, a, b, c, d);
    if (a != VV_HYPERV_INTERFACE_HV1_SIGNATURE) {
        printf("mshv-infra expected Hv#1 CPUID interface signature=0x%x, actual=0x%x\n",
               VV_HYPERV_INTERFACE_HV1_SIGNATURE, a);
        return -1;
    }
    __cpuid(HYPERV_CPUID_FEATURES, a, b, c, d);
    printf("mshv-prerequisite CPUID.%08x EBX=0x%08x\n", HYPERV_CPUID_FEATURES, b);
    if (!(b & HV_CREATE_PARTITIONS) || (b & HV_ISOLATION)) {
        printf("mshv-infra requires CreatePartitions (HV_CREATE_PARTITIONS) without HV_ISOLATION\n");
        return -1;
    }
    struct mshv_fixture f = {.device = -1, .partition = -1, .vp = -1};
    test_result_t result = mshv_create(&f);
    test_result_t cleanup = mshv_cleanup(&f);
    if (result != TEST_PASS || cleanup != TEST_PASS) {
        printf("mshv-infra prerequisite lifecycle failed: device presence is insufficient\n");
        return -1;
    }
    return 0;
}

void mshv_init_context(void *context)
{
    struct mshv_fixture *f = context;
    *f = (struct mshv_fixture){.device = -1, .partition = -1, .vp = -1};
}

test_result_t mshv_cleanup_context(void *context)
{
    return mshv_cleanup(context);
}
