/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML0004 - Complete 128 lifecycles without observable resource exhaustion.
 *
 * UAPI: repeated partition creation, initialization and VP creation.
 *
 * Each cycle creates and initializes a partition and virtual processor (VP),
 * repeats initialization, checks exact RAX set/get and closes all resources.
 * Alternate normal cleanup with closing parent file descriptors (FDs) before
 * using the VP. The console identifies every cycle.
 *
 * Every allocation and operation must succeed. Passing observes no exhaustion
 * over these cycles, but cannot prove complete hypervisor resource cleanup.
 */
#include "lib/mshv.h"

static test_result_t repeated(struct mshv_fixture *f)
{
    const unsigned cycles = 128;
    for (unsigned i = 0; i < cycles; ++i) {
        printf("mshv-cycle %u/%u\n", i + 1, cycles);
        if (mshv_create(f) != TEST_PASS)
            return TEST_FAIL;
        if (i % 2 && mshv_close(&f->device, "close device before partition") != TEST_PASS)
            return TEST_FAIL;
        if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                              "MSHV_INITIALIZE_PARTITION repeated (idempotent)", 0) != TEST_PASS)
            return TEST_FAIL;
        if (i % 2 && mshv_close(&f->partition, "close partition before VP") != TEST_PASS)
            return TEST_FAIL;
        uint64_t seed = i % 2 ? VV_GPR_SEED_DESCENDING : VV_GPR_SEED_LIFECYCLE;
        if (mshv_roundtrip(f, 1, seed) != TEST_PASS)
            return TEST_FAIL;
        if (mshv_cleanup(f) != TEST_PASS)
            return TEST_FAIL;
    }
    return TEST_PASS;
}

REGISTER_MSHV_TEST(ML0004, repeated, "128 lifecycle cycles alternating parent closure orders");
