/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML0005 - Independent partition state survives teardown and recreation.
 *
 * Keep partition B and its VP zero alive across 32 lifecycles of partition A,
 * each also using VP zero. Write distinct RAX/RCX/RDX/RBX patterns and check
 * that writes to either partition leave the other unchanged. Alternate
 * VP-first teardown with closing both parents before the VP.
 *
 * Check B with GET alone after creating and releasing A, before any new SET
 * can mask state corruption. Then require a fresh roundtrip on B. Each new A
 * uses another pattern. Closing descriptors does not prove complete
 * hypervisor resource reclamation.
 */
#include "lib/mshv.h"

static test_result_t partition_isolation(struct mshv_fixture *survivor)
{
    const unsigned cycles = 32;
    const unsigned registers = 4;
    struct mshv_fixture transient;
    test_result_t result = TEST_FAIL;
    uint64_t survivor_seed = VV_GPR_SEED_DESCENDING;
    mshv_init_context(&transient);

    printf("mshv-isolation create persistent B with VP index=0\n");
    if (mshv_create(survivor) != TEST_PASS ||
        mshv_roundtrip(survivor, registers, survivor_seed) != TEST_PASS)
        goto out;
    for (unsigned i = 0; i < cycles; ++i) {
        uint64_t transient_seed = VV_GPR_SEED_ASCENDING ^ i;
        printf("mshv-isolation cycle %u/%u create A with VP index=0\n", i + 1, cycles);
        if (mshv_create(&transient) != TEST_PASS)
            goto out;
        printf("mshv-isolation cycle %u/%u A vp=%d B vp=%d check independent state\n",
               i + 1, cycles, transient.vp, survivor->vp);
        if (mshv_check_gprs(survivor, registers, survivor_seed) != TEST_PASS ||
            mshv_set_gprs(&transient, registers, transient_seed) != TEST_PASS ||
            mshv_check_gprs(survivor, registers, survivor_seed) != TEST_PASS ||
            mshv_check_gprs(&transient, registers, transient_seed) != TEST_PASS)
            goto out;
        survivor_seed = VV_GPR_SEED_DESCENDING ^ ((uint64_t)(i + 1) << 32);
        if (mshv_set_gprs(survivor, registers, survivor_seed) != TEST_PASS ||
            mshv_check_gprs(&transient, registers, transient_seed) != TEST_PASS ||
            mshv_check_gprs(survivor, registers, survivor_seed) != TEST_PASS)
            goto out;

        printf("mshv-isolation cycle %u/%u close A %s\n",
               i + 1, cycles, i % 2 ? "parents first" : "VP first");
        if (i % 2) {
            if (mshv_close(&transient.device, "close A device before partition") != TEST_PASS ||
                mshv_close(&transient.partition, "close A partition before VP") != TEST_PASS ||
                mshv_check_gprs(&transient, registers, transient_seed) != TEST_PASS)
                goto out;
        }
        if (mshv_cleanup(&transient) != TEST_PASS)
            goto out;
        printf("mshv-isolation cycle %u/%u check B after A closure\n", i + 1, cycles);
        if (mshv_check_gprs(survivor, registers, survivor_seed) != TEST_PASS)
            goto out;
        survivor_seed ^= VV_GPR_LOW32_MASK;
        if (mshv_roundtrip(survivor, registers, survivor_seed) != TEST_PASS)
            goto out;
    }
    result = TEST_PASS;
out:
    if (mshv_cleanup(&transient) != TEST_PASS)
        result = TEST_FAIL;
    return result;
}

REGISTER_MSHV_TEST(ML0005, partition_isolation,
                   "Independent partition state across 32 alternating teardown cycles");
