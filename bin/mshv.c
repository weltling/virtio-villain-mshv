/* SPDX-License-Identifier: Apache-2.0 */
#include <cpuid.h>
#include "mshv/test.h"

static int preflight(void)
{
    unsigned a, b, c, d;
    __cpuid(1, a, b, c, d);
    if (!(c & (1U << 31))) {
        printf("mshv-infra expected Hyper-V parent partition, no hypervisor CPUID bit\n");
        return -1;
    }
    __cpuid(0x40000000, a, b, c, d);
    if (a < 0x40000003) {
        printf("mshv-infra Hyper-V feature leaf unavailable: max=0x%x\n", a);
        return -1;
    }
    __cpuid(0x40000001, a, b, c, d);
    if (a != 0x31237648) {
        printf("mshv-infra expected Hv#1 interface=0x31237648, actual=0x%x\n", a);
        return -1;
    }
    __cpuid(0x40000003, a, b, c, d);
    printf("mshv-prerequisite CPUID.40000003 EBX=0x%08x\n", b);
    if (!(b & 1) || (b & (1U << 22))) {
        printf("mshv-infra CreatePartitions privilege required; isolated guests unsupported\n");
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

static void init_context(void *context)
{
    struct mshv_fixture *f = context;
    *f = (struct mshv_fixture){.device = -1, .partition = -1, .vp = -1};
}

static test_result_t cleanup(void *context)
{
    return mshv_cleanup(context);
}

int main(int argc, char **argv)
{
    const struct vv_test_suite suite = {
        .contract = VV_MSHV_CONTRACT,
        .protocol_prefix = "MSHV",
        .begin = __start_mshv_registry,
        .end = __stop_mshv_registry,
        .context_size = sizeof(struct mshv_fixture),
        .preflight = preflight,
        .init_context = init_context,
        .cleanup = cleanup,
    };
    return vv_appliance_main(argc, argv, &suite);
}
