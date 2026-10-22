/* SPDX-License-Identifier: Apache-2.0 */
#include "mshv/test.h"

static test_result_t repeated(struct mshv_fixture *f)
{
    for (unsigned i = 0; i < 128; ++i) {
        printf("mshv-cycle %u/128\n", i + 1);
        if (mshv_create(f) != TEST_PASS)
            return TEST_FAIL;
        if (i % 2 && mshv_close(&f->device, "close device before partition") != TEST_PASS)
            return TEST_FAIL;
        if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                              "MSHV_INITIALIZE_PARTITION repeated (idempotent)", 0) != TEST_PASS)
            return TEST_FAIL;
        if (i % 2 && mshv_close(&f->partition, "close partition before VP") != TEST_PASS)
            return TEST_FAIL;
        uint64_t seed = i % 2 ? 0xfedcba9876543210ULL : 0x123456789abcdef0ULL;
        if (mshv_roundtrip(f, 1, seed) != TEST_PASS)
            return TEST_FAIL;
        if (mshv_cleanup(f) != TEST_PASS)
            return TEST_FAIL;
    }
    return TEST_PASS;
}

REGISTER_MSHV_TEST(ML004, repeated, "128 lifecycle cycles alternating parent closure orders");
